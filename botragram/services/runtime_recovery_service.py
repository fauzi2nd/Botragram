"""Recover an active trading position after an application restart."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import Final, Protocol

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.engine import RiskEngine
from botragram.enums import (
    Interval,
    MarketType,
    OrderSide,
    OrderType,
    PositionSide,
    SignalType,
    StrategyType,
    TradeMode,
)
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Order, Position
from botragram.repositories import (
    CandleRepository,
    PositionRepository,
    SignalRepository,
)
from botragram.services.position_service import PositionService

__all__ = ["RuntimeRecoveryService"]


_FIRST_TICK_TIMEOUT_SECONDS: Final[float] = 15.0
_FIRST_TICK_POLL_SECONDS: Final[float] = 0.05
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class MarketStreamController(Protocol):
    """Control the process-wide market stream used by runtime recovery."""

    async def start_market_stream(self) -> bool:
        """Start the selected market stream."""
        ...

    async def stop_market_stream(self) -> bool:
        """Stop the selected market stream."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class RuntimeRecoveryService:
    """Restore one active position without bypassing live safety gates."""

    trade_mode: TradeMode
    market_type: MarketType
    runtime_control: TradingRuntimeControl
    stream_controller: MarketStreamController
    position_service: PositionService
    position_repository: PositionRepository
    signal_repository: SignalRepository
    candle_repository: CandleRepository
    exchange_client: BaseExchangeClient
    risk_engine: RiskEngine
    first_tick_timeout_seconds: float = _FIRST_TICK_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """Validate recovery timing."""
        if self.first_tick_timeout_seconds <= 0:
            raise ValueError("First stream tick timeout must be greater than zero")

    async def recover(self) -> bool:
        """Recover one position and resume only when every safety gate is ready."""
        persisted_positions = tuple(await self.position_repository.get_open_positions())
        positions = (
            await self._synchronize_live_positions(
                persisted_positions=persisted_positions,
            )
            if self.trade_mode is TradeMode.LIVE
            else persisted_positions
        )

        if not positions:
            return False

        if len(positions) != 1:
            self.runtime_control.set_position_protection_ready(False)
            _LOGGER.critical(
                "Automatic recovery requires exactly one active position: count=%d",
                len(positions),
            )
            return False

        position = await self._restore_metadata(position=positions[0])

        if position is None:
            _LOGGER.critical(
                "Automatic recovery blocked because position metadata could not "
                "be reconstructed unambiguously: symbol=%s",
                positions[0].symbol,
            )
            return False

        await self.position_repository.save(position=position)

        if self.trade_mode is TradeMode.LIVE:
            if self.market_type is not MarketType.FUTURES:
                self.runtime_control.set_position_protection_ready(False)
                _LOGGER.critical(
                    "Automatic live position recovery currently requires FUTURES"
                )
                return False

            self.runtime_control.set_position_protection_ready(False)

            try:
                position = await self._ensure_live_protection(position=position)
            except Exception:
                _LOGGER.exception(
                    "Live recovery blocked because SL/TP protection could not be "
                    "verified: symbol=%s",
                    position.symbol,
                )
                return False

            self.runtime_control.set_position_protection_ready(True)

        self.runtime_control.restore_configuration(
            symbol=position.symbol,
            interval=self._require_interval(position),
            strategy_type=self._require_strategy(position),
        )
        await self.stream_controller.start_market_stream()

        try:
            await self._wait_for_first_tick()
        except TimeoutError:
            await self.stream_controller.stop_market_stream()
            _LOGGER.error(
                "Automatic recovery timed out waiting for first stream tick: "
                "symbol=%s timeout_seconds=%.1f",
                position.symbol,
                self.first_tick_timeout_seconds,
            )
            return False

        self.runtime_control.resume()
        _LOGGER.info(
            "Active position recovered automatically: mode=%s symbol=%s side=%s "
            "interval=%s strategy=%s",
            self.trade_mode.value,
            position.symbol,
            position.side.value,
            self._require_interval(position).value,
            self._require_strategy(position).value,
        )
        return True

    async def _synchronize_live_positions(
        self,
        *,
        persisted_positions: Sequence[Position],
    ) -> tuple[Position, ...]:
        """Read live positions from the exchange and preserve local metadata."""
        previous_by_symbol = {
            position.symbol.upper(): position for position in persisted_positions
        }
        exchange_positions = tuple(await self.position_service.sync())
        merged: list[Position] = []

        for position in exchange_positions:
            previous = previous_by_symbol.get(position.symbol.upper())
            merged_position = replace(
                position,
                interval=(previous.interval if previous is not None else None),
                strategy_type=(
                    previous.strategy_type if previous is not None else None
                ),
            )
            await self.position_repository.save(position=merged_position)
            merged.append(merged_position)

        return tuple(merged)

    async def _restore_metadata(self, *, position: Position) -> Position | None:
        """Reconstruct missing paper metadata from its exact entry history."""
        if position.interval is not None and position.strategy_type is not None:
            return position

        expected_signal_type = (
            SignalType.BUY if position.side is PositionSide.LONG else SignalType.SELL
        )
        signals = tuple(
            signal
            for signal in await self.signal_repository.get_between(
                start_time=position.opened_at,
                end_time=position.opened_at,
                symbol=position.symbol,
                signal_type=expected_signal_type,
            )
            if signal.generated_at == position.opened_at
        )

        if len(signals) != 1:
            return None

        try:
            strategy_type = StrategyType(signals[0].strategy_name)
        except ValueError:
            return None

        matching_intervals: list[Interval] = []

        for interval in Interval:
            candles = await self.candle_repository.get_between(
                symbol=position.symbol,
                interval=interval,
                start_time=position.opened_at - timedelta(seconds=interval.seconds),
                end_time=position.opened_at,
            )

            if any(candle.close_time == position.opened_at for candle in candles):
                matching_intervals.append(interval)

        if len(matching_intervals) != 1:
            return None

        restored = replace(
            position,
            interval=matching_intervals[0],
            strategy_type=strategy_type,
        )
        _LOGGER.warning(
            "Legacy position recovery metadata reconstructed from entry history: "
            "symbol=%s interval=%s strategy=%s",
            restored.symbol,
            matching_intervals[0].value,
            strategy_type.value,
        )
        return restored

    async def _ensure_live_protection(self, *, position: Position) -> Position:
        """Reconcile one live position with exactly one SL and one TP order."""
        protection_orders = await self.exchange_client.get_open_protection_orders(
            symbol=position.symbol,
        )
        stop_order = self._find_protection_order(
            orders=protection_orders,
            position=position,
            order_type=OrderType.STOP_MARKET,
        )
        take_profit_order = self._find_protection_order(
            orders=protection_orders,
            position=position,
            order_type=OrderType.TAKE_PROFIT_MARKET,
        )
        calculated_stop, calculated_take_profit = (
            self.risk_engine.calculate_protection_levels(
                side=position.side,
                entry_price=position.entry_price,
                strategy_type=position.strategy_type,
            )
        )

        if stop_order is None or take_profit_order is None:
            await self.exchange_client.create_protection_orders(
                symbol=position.symbol,
                side=self._closing_side(position.side),
                quantity=position.quantity,
                stop_loss=calculated_stop if stop_order is None else None,
                take_profit=(
                    calculated_take_profit if take_profit_order is None else None
                ),
            )
            protection_orders = await self.exchange_client.get_open_protection_orders(
                symbol=position.symbol,
            )
            stop_order = self._find_protection_order(
                orders=protection_orders,
                position=position,
                order_type=OrderType.STOP_MARKET,
            )
            take_profit_order = self._find_protection_order(
                orders=protection_orders,
                position=position,
                order_type=OrderType.TAKE_PROFIT_MARKET,
            )

        if stop_order is None or take_profit_order is None:
            raise RuntimeError("Exchange did not confirm both SL and TP orders")

        if stop_order.stop_price is None or take_profit_order.stop_price is None:
            raise RuntimeError("Exchange protection order is missing a trigger price")

        protected = replace(
            position,
            stop_loss=stop_order.stop_price,
            take_profit=take_profit_order.stop_price,
        )
        await self.position_repository.save(position=protected)
        _LOGGER.info(
            "Live position protection verified: symbol=%s stop_loss=%s take_profit=%s",
            position.symbol,
            protected.stop_loss,
            protected.take_profit,
        )
        return protected

    @staticmethod
    def _find_protection_order(
        *,
        orders: Sequence[Order],
        position: Position,
        order_type: OrderType,
    ) -> Order | None:
        """Find a matching protection order and reject insufficient coverage."""
        closing_side = RuntimeRecoveryService._closing_side(position.side)
        matching: list[Order] = []

        for order in orders:
            if (
                order.symbol.upper() != position.symbol.upper()
                or order.side is not closing_side
                or order.order_type is not order_type
            ):
                continue

            if order.quantity < position.quantity:
                raise RuntimeError(
                    f"{order_type.value} quantity does not cover the live position"
                )

            if order.stop_price is not None:
                matching.append(order)

        if not matching:
            return None

        return (
            max(matching, key=lambda order: order.stop_price or Decimal("0"))
            if position.side is PositionSide.LONG
            else min(matching, key=lambda order: order.stop_price or Decimal("0"))
        )

    async def _wait_for_first_tick(self) -> None:
        """Wait until the restored stream has delivered one validated ticker."""
        async with asyncio.timeout(self.first_tick_timeout_seconds):
            while self.runtime_control.get_stream_telemetry().event_count == 0:
                await asyncio.sleep(_FIRST_TICK_POLL_SECONDS)

    @staticmethod
    def _closing_side(side: PositionSide) -> OrderSide:
        """Return the reduce-only order side for a position."""
        return OrderSide.SELL if side is PositionSide.LONG else OrderSide.BUY

    @staticmethod
    def _require_interval(position: Position) -> Interval:
        """Return recovery interval after metadata restoration."""
        if position.interval is None:
            raise RuntimeError("Recovered position interval is missing")

        return position.interval

    @staticmethod
    def _require_strategy(position: Position) -> StrategyType:
        """Return recovery strategy after metadata restoration."""
        if position.strategy_type is None:
            raise RuntimeError("Recovered position strategy is missing")

        return position.strategy_type
