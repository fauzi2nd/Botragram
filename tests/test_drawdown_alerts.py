"""
Botragram

Description:
    Regression tests for proactive Telegram risk and drawdown alerts.

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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import NotificationType
from botragram.models import LiveEquityHighWaterMark, Notification
from botragram.repositories import LiveEquityHighWaterRepository
from botragram.services.live_account_drawdown_service import (
    DrawdownNotificationPublisher,
    LiveAccountDrawdownService,
)
from botragram.telegram.messages import get_drawdown_alert_message


@dataclass(slots=True)
class _MemoryHighWaterRepository(LiveEquityHighWaterRepository):
    """Minimal in-memory high-water repository for test isolation."""

    mark: LiveEquityHighWaterMark | None = None

    async def get(self, *, asset: str) -> LiveEquityHighWaterMark | None:
        if self.mark is None or self.mark.asset != asset.upper():
            return None
        return self.mark

    async def save_if_greater(
        self,
        *,
        asset: str,
        equity: Decimal,
        observed_at: datetime,
    ) -> LiveEquityHighWaterMark:
        existing = await self.get(asset=asset)
        if existing is None or equity > existing.equity:
            self.mark = LiveEquityHighWaterMark(
                asset=asset.upper(),
                equity=equity,
                observed_at=observed_at,
            )
        if self.mark is None:
            raise RuntimeError("Test high-water mark was not persisted")
        return self.mark


@dataclass(slots=True)
class _RecordingPublisher(DrawdownNotificationPublisher):
    """Record published notifications for assertion."""

    notifications: list[Notification] = field(default_factory=list[Notification])
    should_fail: bool = False

    async def publish(self, *, notification: Notification) -> None:
        if self.should_fail:
            raise ConnectionError("Telegram network failure")
        self.notifications.append(notification)


def test_drawdown_alert_message_formatting() -> None:
    """Validate HTML formatting of warning and critical drawdown alert messages."""
    warning_msg = get_drawdown_alert_message(
        current_drawdown_pct=Decimal("0.076"),
        max_drawdown_pct=Decimal("0.10"),
        current_equity=Decimal("924.0"),
        high_water_equity=Decimal("1000.0"),
        asset="USDT",
        level="WARNING",
    )
    assert "DRAWDOWN WARNING" in warning_msg
    assert "7.60%" in warning_msg
    assert "10.00%" in warning_msg
    assert "924.00 USDT" in warning_msg

    critical_msg = get_drawdown_alert_message(
        current_drawdown_pct=Decimal("0.092"),
        max_drawdown_pct=Decimal("0.10"),
        current_equity=Decimal("908.0"),
        high_water_equity=Decimal("1000.0"),
        asset="USDT",
        level="CRITICAL",
    )
    assert "CRITICAL DRAWDOWN ALERT" in critical_msg
    assert "🚨" in critical_msg
    assert "9.20%" in critical_msg


@pytest.mark.asyncio
async def test_drawdown_alert_triggered_at_thresholds() -> None:
    """Trigger WARNING at 75% and CRITICAL at 90% of max drawdown limit."""
    repository = _MemoryHighWaterRepository(
        mark=LiveEquityHighWaterMark(
            asset="USDT",
            equity=Decimal("1000"),
            observed_at=datetime(2026, 9, 9, tzinfo=UTC),
        )
    )
    publisher = _RecordingPublisher()
    service = LiveAccountDrawdownService(
        repository=repository,
        asset="USDT",
        notification_publisher=publisher,
        max_drawdown_pct=Decimal("0.10"),  # 10% max DD
        warning_threshold_ratio=Decimal("0.75"),  # 7.5% DD
        critical_threshold_ratio=Decimal("0.90"),  # 9.0% DD
        alert_cooldown_seconds=60.0,
    )

    # 1. Normal equity 950 (5% DD) -> below 7.5% -> no alert
    dd = await service.get_current_drawdown_pct(equity=Decimal("950"))
    assert dd == Decimal("0.05")
    assert len(publisher.notifications) == 0

    # 2. Equity 920 (8% DD) -> above 7.5% WARNING -> emits WARNING notification
    dd = await service.get_current_drawdown_pct(equity=Decimal("920"))
    assert dd == Decimal("0.08")
    assert len(publisher.notifications) == 1
    assert publisher.notifications[0].level == NotificationType.WARNING
    assert "WARNING" in publisher.notifications[0].title

    # 3. Repeat equity 915 within cooldown -> no duplicate WARNING alert
    await service.get_current_drawdown_pct(equity=Decimal("915"))
    assert len(publisher.notifications) == 1

    # 4. Equity 905 (9.5% DD) -> crosses CRITICAL (9.0%) -> emits CRITICAL alert
    dd = await service.get_current_drawdown_pct(equity=Decimal("905"))
    assert dd == Decimal("0.095")
    assert len(publisher.notifications) == 2
    assert publisher.notifications[1].level == NotificationType.RISK
    assert "CRITICAL" in publisher.notifications[1].title


@pytest.mark.asyncio
async def test_drawdown_alert_publisher_failure_non_blocking() -> None:
    """Ensure publisher failure is handled without breaking drawdown check."""
    repository = _MemoryHighWaterRepository(
        mark=LiveEquityHighWaterMark(
            asset="USDT",
            equity=Decimal("1000"),
            observed_at=datetime(2026, 9, 9, tzinfo=UTC),
        )
    )
    publisher = _RecordingPublisher(should_fail=True)
    service = LiveAccountDrawdownService(
        repository=repository,
        asset="USDT",
        notification_publisher=publisher,
        max_drawdown_pct=Decimal("0.10"),
    )

    # Should not raise exception even when publisher fails
    dd = await service.get_current_drawdown_pct(equity=Decimal("900"))
    assert dd == Decimal("0.1")
