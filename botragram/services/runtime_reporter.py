"""Runtime health and portfolio notification observer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from typing import Final, Protocol

from botragram.enums import NotificationType, TradeMode
from botragram.models import Notification, TradingResult
from botragram.repositories import PositionRepository
from botragram.services.health_service import HealthService
from botragram.services.paper_trading_service import NotificationPublisher
from botragram.telegram.messages import get_runtime_portfolio_message
from botragram.utils.formatter import format_currency

__all__ = ["RuntimeReporter"]


_DEFAULT_REPORT_EVERY_CYCLES: Final[int] = 4
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class PortfolioBalanceProvider(Protocol):
    """Read available portfolio balance for reporting."""

    async def get_available_balance(self) -> Decimal:
        """Return available balance."""
        ...


@dataclass(slots=True, kw_only=True)
class RuntimeReporter:
    """Publish health, failure, and periodic portfolio summaries."""

    health_service: HealthService
    paper_trading_service: PortfolioBalanceProvider
    position_repository: PositionRepository
    notification_publisher: NotificationPublisher
    trade_mode: TradeMode
    symbol: str
    report_every_cycles: int = _DEFAULT_REPORT_EVERY_CYCLES
    _completed_cycles: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        """Validate reporting configuration."""
        if self.report_every_cycles <= 0:
            raise ValueError("Runtime report cycle interval must be greater than zero")

    async def on_started(self) -> None:
        """Publish startup dependency health and portfolio state."""
        health = await self.health_service.check()
        status = "HEALTHY" if health.healthy else "DEGRADED"
        balance_text = "N/A"
        position_count_text = "N/A"

        try:
            positions = await self.position_repository.get_open_positions()
            position_count_text = str(len(positions))
        except Exception:
            _LOGGER.exception("Startup position health snapshot failed")

        if self.trade_mode is TradeMode.PAPER:
            try:
                balance = await self.paper_trading_service.get_available_balance()
                balance_text = format_currency(balance, symbol="USDT")
            except Exception:
                _LOGGER.exception("Startup balance health snapshot failed")

        message = (
            "<b>Botragram Startup</b>\n\n"
            f"<b>Status:</b> {status}\n"
            f"<b>Mode:</b> {self.trade_mode.value}\n"
            f"<b>Symbol:</b> {escape(self.symbol)}\n"
            f"<b>Database:</b> {'OK' if health.database_healthy else 'FAILED'}\n"
            f"<b>Exchange:</b> {'OK' if health.exchange_healthy else 'FAILED'}\n"
            f"<b>Open Positions:</b> {position_count_text}\n"
            f"<b>Available Balance:</b> {balance_text}"
        )
        await self._publish(
            title="Runtime startup health",
            message=message,
            level=NotificationType.SYSTEM,
        )

    async def on_cycle_completed(self, *, result: TradingResult) -> None:
        """Publish portfolio summary at the configured cycle cadence."""
        del result
        self._completed_cycles += 1

        if (
            self.trade_mode is not TradeMode.PAPER
            or self._completed_cycles % self.report_every_cycles != 0
        ):
            return

        balance = await self.paper_trading_service.get_available_balance()
        positions = await self.position_repository.get_open_positions()
        await self._publish(
            title="Periodic paper portfolio report",
            message=get_runtime_portfolio_message(
                available_balance=balance,
                positions=positions,
                completed_cycles=self._completed_cycles,
            ),
            level=NotificationType.INFO,
        )

    async def on_cycle_failed(
        self,
        *,
        error: Exception,
        consecutive_failures: int,
        maximum_failures: int,
    ) -> None:
        """Publish a sanitized runtime failure alert."""
        message = (
            "<b>Trading Cycle Failed</b>\n\n"
            f"<b>Error Type:</b> {type(error).__name__}\n"
            f"<b>Attempt:</b> {consecutive_failures}/{maximum_failures}\n"
            "Detail sensitif hanya dicatat di log lokal."
        )
        await self._publish(
            title="Trading cycle failure",
            message=message,
            level=NotificationType.ERROR,
        )

    async def on_stopped(self) -> None:
        """Publish deterministic runtime shutdown status."""
        await self._publish(
            title="Trading runtime stopped",
            message="<b>Botragram trading runtime stopped.</b>",
            level=NotificationType.SYSTEM,
        )

    async def _publish(
        self,
        *,
        title: str,
        message: str,
        level: NotificationType,
    ) -> None:
        """Publish without allowing monitoring failure to affect trading."""
        notification = Notification(
            title=title,
            message=message,
            level=level,
            created_at=datetime.now(timezone.utc),
        )

        try:
            await self.notification_publisher.publish(notification=notification)
        except Exception:
            _LOGGER.exception("Runtime report delivery failed: %s", title)
