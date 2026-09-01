"""Runtime health and portfolio notification observer."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from typing import Final, Protocol, runtime_checkable

from botragram.enums import NotificationType, TradeMode
from botragram.models import Account, Notification, Position, TradingResult
from botragram.services.health_service import HealthService
from botragram.services.paper_trading_service import NotificationPublisher
from botragram.telegram.messages import get_runtime_portfolio_message
from botragram.utils.formatter import format_currency

__all__ = ["RuntimeReporter"]


_DEFAULT_REPORT_EVERY_CYCLES: Final[int] = 4
_DEFAULT_QUOTE_ASSET: Final[str] = "USDT"
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class PortfolioBalanceProvider(Protocol):
    """Read available portfolio balance for reporting."""

    async def get_available_balance(self) -> Decimal:
        """Return available balance."""
        ...


class _OpenPositionProvider(Protocol):
    """Read stored open positions for runtime reporting."""

    async def get_open_positions(self) -> Sequence[Position]:
        """Return the current stored open positions."""
        ...


@runtime_checkable
class ExchangeAccountSnapshotProvider(Protocol):
    """Read one normalized exchange account snapshot for startup reporting."""

    async def get_account(self) -> Account:
        """Return current exchange account information."""
        ...


@dataclass(slots=True, kw_only=True)
class RuntimeReporter:
    """Publish health, failure, and periodic portfolio summaries."""

    health_service: HealthService
    paper_trading_service: PortfolioBalanceProvider
    position_repository: _OpenPositionProvider
    notification_publisher: NotificationPublisher
    trade_mode: TradeMode
    symbol: str
    quote_asset: str = _DEFAULT_QUOTE_ASSET
    report_every_cycles: int = _DEFAULT_REPORT_EVERY_CYCLES
    _completed_cycles: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        """Validate reporting configuration."""
        if self.report_every_cycles <= 0:
            raise ValueError("Runtime report cycle interval must be greater than zero")

        self.quote_asset = self.quote_asset.strip().upper()
        if not self.quote_asset:
            raise ValueError("Runtime report quote asset must not be empty")

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

        try:
            balance = await self._get_startup_available_balance()
            if balance is not None:
                balance_text = format_currency(
                    balance, symbol=self.quote_asset, group_thousands=True
                )
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

    async def _get_startup_available_balance(self) -> Decimal | None:
        """Return one startup balance from the mode-authoritative provider."""
        if self.trade_mode is TradeMode.PAPER:
            return await self.paper_trading_service.get_available_balance()

        exchange = self.health_service.exchange
        if not isinstance(exchange, ExchangeAccountSnapshotProvider):
            return None

        account = await exchange.get_account()
        matching_balances = tuple(
            balance
            for balance in account.balances
            if balance.asset.upper() == self.quote_asset
        )
        if len(matching_balances) > 1:
            raise RuntimeError(
                "Exchange returned multiple startup balances for asset "
                f"{self.quote_asset!r}"
            )
        if not matching_balances:
            return Decimal("0")
        return matching_balances[0].free

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
        """Publish a sanitized runtime failure alert at maximum threshold."""
        if consecutive_failures < maximum_failures:
            return

        failure_counter = (
            f"<b>Consecutive Cycle Failures:</b> "
            f"{consecutive_failures}/{maximum_failures}\n"
        )
        recovery_note = (
            "<b>24/7 Recovery:</b> separate autonomous safety recovery applies "
            "when eligible.\n"
            if self.trade_mode is TradeMode.LIVE
            else ""
        )
        message = (
            "<b>Trading Cycle Failed</b>\n\n"
            f"<b>Error Type:</b> {type(error).__name__}\n"
            f"{failure_counter}"
            f"{recovery_note}"
            "Sensitive detail is recorded only in the local log."
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
