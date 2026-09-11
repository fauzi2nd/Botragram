"""
Botragram

Description:
    In-flight position exit evaluation and early execution orchestration service.

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
import logging
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final, Protocol
from uuid import uuid4

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine.position_exit_engine import PositionExitEngine
from botragram.enums import (
    Interval,
    NotificationType,
    PositionExitAction,
    TradeMode,
)
from botragram.models import (
    Candle,
    Notification,
    Order,
    Position,
    PositionExitDecision,
    Signal,
    TradingResult,
)
from botragram.repositories import PositionRepository

__all__ = [
    "PositionExitService",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_DEFAULT_CANDLE_LIMIT: Final[int] = 50
_CLIENT_ORDER_ID_PREFIX: Final[str] = "ecl-"


# =============================================================================
# Protocols
# =============================================================================
class _MarketCandleProvider(Protocol):
    """Provide historical market candles."""

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
    ) -> Sequence[Candle]:
        """Return candlestick bars."""
        ...


class _StrategySignalProvider(Protocol):
    """Generate strategy signals for closed candles."""

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate and save a signal from candles."""
        ...


class _LiveExchangeExitProvider(Protocol):
    """Cancel open orders and submit reduce-only exact position closes."""

    async def cancel_all_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Cancel all pending orders."""
        ...

    async def close_position_exact(
        self,
        *,
        position: Position,
        client_order_id: str,
    ) -> Order:
        """Submit one reduce-only close order."""
        ...


class _PaperPositionExitProvider(Protocol):
    """Execute simulated position closes in paper mode."""

    async def close_position_for_early_exit(
        self,
        *,
        symbol: str,
        current_price: Decimal,
        closed_at: datetime,
        reason: str = "Early Cut Loss",
    ) -> TradingResult | None:
        """Close one paper position with an explicit early-exit reason."""
        ...


class _PositionLifecycleCoordinator(Protocol):
    """Serialize lifecycle mutations."""

    def hold(self, *, symbol: str) -> AbstractAsyncContextManager[None]:
        """Acquire a per-symbol lifecycle lock."""
        ...


class _ExitNotificationPublisher(Protocol):
    """Publish notifications to external channels."""

    async def publish(self, *, notification: Notification) -> None:
        """Publish a notification."""
        ...


# =============================================================================
# Service Class
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class PositionExitService:
    """Orchestrate in-flight position health evaluation and early invalidation exits."""

    engine: PositionExitEngine
    market_service: _MarketCandleProvider
    strategy_service: _StrategySignalProvider | None = None
    live_exchange: _LiveExchangeExitProvider | None = None
    paper_trading_service: _PaperPositionExitProvider | None = None
    lifecycle_coordinator: _PositionLifecycleCoordinator | None = None
    notification_publisher: _ExitNotificationPublisher | None = None
    position_repository: PositionRepository | None = None
    trade_mode: TradeMode = TradeMode.LIVE

    async def evaluate_active_positions(
        self,
        *,
        interval: Interval,
        candle_limit: int = _DEFAULT_CANDLE_LIMIT,
    ) -> tuple[PositionExitDecision, ...]:
        """Query currently open positions and evaluate them for early exit.

        Args:
            interval: Trading timeframe for the completed candle.
            candle_limit: Number of candles required for evaluation.

        Returns:
            Tuple of PositionExitDecision instances for evaluated positions.
        """
        if not self.engine.enabled or self.position_repository is None:
            return ()

        positions = await self.position_repository.get_open_positions()
        return await self.evaluate_open_positions(
            positions=positions,
            interval=interval,
            candle_limit=candle_limit,
        )

    async def evaluate_open_positions(
        self,
        *,
        positions: Sequence[Position],
        interval: Interval,
        candle_limit: int = _DEFAULT_CANDLE_LIMIT,
    ) -> tuple[PositionExitDecision, ...]:
        """Evaluate open positions upon candle close and execute early exits.

        Args:
            positions: Authoritative sequence of currently open positions.
            interval: Trading timeframe for the completed candle.
            candle_limit: Number of candles required for evaluation.

        Returns:
            Tuple of PositionExitDecision instances for each evaluated position.
        """
        if not self.engine.enabled:
            return ()

        decisions: list[PositionExitDecision] = []

        for position in positions:
            if position.quantity <= Decimal("0"):
                continue

            try:
                decision = await self._evaluate_single_position(
                    position=position,
                    interval=interval,
                    candle_limit=candle_limit,
                )
            except Exception as error:
                _LOGGER.exception(
                    "Error evaluating in-flight exit for %s: %s",
                    position.symbol,
                    error,
                )
                continue

            decisions.append(decision)

            if decision.action is PositionExitAction.EARLY_CUT_LOSS:
                _LOGGER.warning(
                    "Early Cut Loss triggered for %s %s: reason=%s (confidence=%.2f)",
                    position.symbol,
                    position.side.value,
                    decision.reason,
                    decision.confidence,
                )
                try:
                    await self._execute_early_exit(
                        position=position,
                        decision=decision,
                    )
                except Exception as error:
                    _LOGGER.exception(
                        "Failed to execute early exit for %s: %s",
                        position.symbol,
                        error,
                    )

        return tuple(decisions)

    async def _evaluate_single_position(
        self,
        *,
        position: Position,
        interval: Interval,
        candle_limit: int,
    ) -> PositionExitDecision:
        """Fetch market data and evaluate exit criteria for one position."""
        candles = await self.market_service.get_candles(
            symbol=position.symbol,
            interval=interval,
            limit=candle_limit,
        )

        strategy_signal: Signal | None = None
        if self.engine.check_opposite_signal and self.strategy_service is not None:
            try:
                strategy_signal = await self.strategy_service.generate_and_save(
                    candles=candles,
                )
            except Exception as error:
                _LOGGER.debug(
                    "Could not generate strategy signal for %s: %s",
                    position.symbol,
                    error,
                )

        return self.engine.evaluate(
            position=position,
            candles=candles,
            strategy_signal=strategy_signal,
        )

    async def _execute_early_exit(
        self,
        *,
        position: Position,
        decision: PositionExitDecision,
    ) -> None:
        """Execute an early cut loss across live or paper environments."""
        if self.trade_mode is TradeMode.LIVE:
            if self.live_exchange is None:
                raise RuntimeError("LIVE early exit requires a live exchange client")

            client_order_id = f"{_CLIENT_ORDER_ID_PREFIX}{uuid4().hex[:12]}"
            if self.lifecycle_coordinator is not None:
                async with self.lifecycle_coordinator.hold(symbol=position.symbol):
                    await self._execute_live_close(
                        position=position,
                        client_order_id=client_order_id,
                    )
            else:
                await self._execute_live_close(
                    position=position,
                    client_order_id=client_order_id,
                )
        elif (
            self.trade_mode is TradeMode.PAPER
            and self.paper_trading_service is not None
        ):
            close_price = decision.trigger_price or position.current_price
            await self.paper_trading_service.close_position_for_early_exit(
                symbol=position.symbol,
                current_price=close_price,
                closed_at=datetime.now(timezone.utc),
                reason=f"Early Cut Loss: {decision.reason}",
            )

        await self._notify_early_exit(position=position, decision=decision)

    async def _execute_live_close(
        self,
        *,
        position: Position,
        client_order_id: str,
    ) -> None:
        """Cancel server-side bracket algo orders and submit market close."""
        assert self.live_exchange is not None

        try:
            await self.live_exchange.cancel_all_orders(symbol=position.symbol)
            _LOGGER.info(
                "Cancelled pending bracket orders for %s before early close",
                position.symbol,
            )
        except Exception as error:
            _LOGGER.warning(
                "Failed to cancel bracket orders before early close for %s: %s",
                position.symbol,
                error,
            )

        await self.live_exchange.close_position_exact(
            position=position,
            client_order_id=client_order_id,
        )
        _LOGGER.info(
            "Submitted exact reduce-only close order for %s: client_order_id=%s",
            position.symbol,
            client_order_id,
        )

    async def _notify_early_exit(
        self,
        *,
        position: Position,
        decision: PositionExitDecision,
    ) -> None:
        """Deliver an informational alert to Telegram subscribers."""
        if self.notification_publisher is None:
            return

        exit_price = decision.trigger_price or position.current_price
        message = (
            f"<b>🚨 EARLY CUT LOSS EXECUTED</b>\n\n"
            f"<b>Symbol:</b> <code>{position.symbol}</code>\n"
            f"<b>Side:</b> {position.side.value.upper()}\n"
            f"<b>Entry Price:</b> {position.entry_price}\n"
            f"<b>Exit Price:</b> {exit_price}\n"
            f"<b>Floating PnL:</b> {position.unrealized_pnl} USDT\n"
            f"<b>Reason:</b> {decision.reason}\n\n"
            f"<i>Position closed early on candle close to prevent "
            f"full Stop Loss hit.</i>"
        )
        try:
            await self.notification_publisher.publish(
                notification=Notification(
                    title=f"Early Cut Loss: {position.symbol}",
                    message=message,
                    level=NotificationType.WARNING,
                    created_at=datetime.now(timezone.utc),
                )
            )
        except Exception as error:
            _LOGGER.warning(
                "Failed to deliver early exit notification for %s: %s",
                position.symbol,
                error,
            )
