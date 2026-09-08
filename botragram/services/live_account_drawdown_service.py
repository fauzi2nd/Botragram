"""
Botragram

Description:
    Durable account-equity drawdown calculation and proactive risk alerts
    for LIVE risk checks.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import NotificationType
from botragram.models import Notification
from botragram.repositories import LiveEquityHighWaterRepository
from botragram.telegram.messages import get_drawdown_alert_message

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "DrawdownNotificationPublisher",
    "LiveAccountDrawdownService",
]

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Protocols
# =============================================================================
class DrawdownNotificationPublisher(Protocol):
    """Publish risk notifications to an external channel."""

    async def publish(self, *, notification: Notification) -> None:
        """Publish one notification."""
        ...


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True)
class LiveAccountDrawdownService:
    """Maintain a durable high-water mark and calculate current drawdown."""

    repository: LiveEquityHighWaterRepository
    asset: str
    notification_publisher: DrawdownNotificationPublisher | None = None
    max_drawdown_pct: Decimal = Decimal("0.10")
    warning_threshold_ratio: Decimal = Decimal("0.75")
    critical_threshold_ratio: Decimal = Decimal("0.90")
    alert_cooldown_seconds: float = 900.0
    _high_water_equity: Decimal | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _last_alert_at: dict[str, float] = field(
        default_factory=dict[str, float], init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Normalize the configured collateral asset."""
        normalized_asset = self.asset.strip().upper()
        if not normalized_asset:
            raise ValueError("LIVE drawdown asset must not be empty")
        self.asset = normalized_asset

    async def observe(self, *, equity: Decimal) -> Decimal:
        """Record equity when it establishes a new durable high-water mark."""
        self._validate_equity(equity)
        async with self._lock:
            high_water_equity = self._high_water_equity
            if high_water_equity is None:
                existing = await self.repository.get(asset=self.asset)
                high_water_equity = (
                    existing.equity if existing is not None else _DECIMAL_ZERO
                )
            if equity > high_water_equity:
                saved = await self.repository.save_if_greater(
                    asset=self.asset,
                    equity=equity,
                    observed_at=datetime.now(UTC),
                )
                high_water_equity = saved.equity
            self._high_water_equity = high_water_equity
            return high_water_equity

    async def get_current_drawdown_pct(self, *, equity: Decimal) -> Decimal:
        """Return the current fraction below the durable account high-water mark."""
        high_water_equity = await self.observe(equity=equity)
        if high_water_equity <= _DECIMAL_ZERO:
            raise RuntimeError("LIVE account equity high-water mark is invalid")
        drawdown_pct = max(
            _DECIMAL_ZERO,
            (high_water_equity - equity) / high_water_equity,
        )
        if (
            self.notification_publisher is not None
            and self.max_drawdown_pct > _DECIMAL_ZERO
        ):
            await self._check_and_send_alert(
                current_drawdown_pct=drawdown_pct,
                current_equity=equity,
                high_water_equity=high_water_equity,
            )
        return drawdown_pct

    async def _check_and_send_alert(
        self,
        *,
        current_drawdown_pct: Decimal,
        current_equity: Decimal,
        high_water_equity: Decimal,
    ) -> None:
        """Publish alert when drawdown crosses warning or critical thresholds."""
        if self.notification_publisher is None:
            return

        critical_threshold = self.max_drawdown_pct * self.critical_threshold_ratio
        warning_threshold = self.max_drawdown_pct * self.warning_threshold_ratio

        level: str | None = None
        if current_drawdown_pct >= critical_threshold:
            level = "CRITICAL"
        elif current_drawdown_pct >= warning_threshold:
            level = "WARNING"

        if level is None:
            return

        now = monotonic()
        last_alert = self._last_alert_at.get(level, 0.0)
        if now - last_alert < self.alert_cooldown_seconds:
            return

        self._last_alert_at[level] = now
        title = (
            f"Drawdown Alert [{level}]: {current_drawdown_pct * Decimal('100'):.1f}%"
        )
        message = get_drawdown_alert_message(
            current_drawdown_pct=current_drawdown_pct,
            max_drawdown_pct=self.max_drawdown_pct,
            current_equity=current_equity,
            high_water_equity=high_water_equity,
            asset=self.asset,
            level=level,
        )
        notification = Notification(
            title=title,
            message=message,
            level=(
                NotificationType.RISK
                if level == "CRITICAL"
                else NotificationType.WARNING
            ),
            created_at=datetime.now(UTC),
        )
        try:
            await self.notification_publisher.publish(notification=notification)
        except Exception:
            _LOGGER.exception("Failed to publish drawdown alert notification")

    @staticmethod
    def _validate_equity(equity: Decimal) -> None:
        """Reject non-finite or non-positive observed equity."""
        if not equity.is_finite() or equity <= _DECIMAL_ZERO:
            raise ValueError("LIVE account equity must be finite and positive")
