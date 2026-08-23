"""Event-driven stepped profit protection for active positions."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from decimal import Decimal
from time import monotonic
from typing import Final

from botragram.enums import OrderSide, OrderType, PositionSide, TradeMode
from botragram.exceptions import VenueRuleValidationError
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Position, Ticker
from botragram.repositories import PositionRepository

__all__ = ["PositionProtectionManager"]


_POSITION_REFRESH_SECONDS: Final[float] = 1.0
_FAILURE_RETRY_SECONDS: Final[float] = 5.0
_PROGRESS_THRESHOLDS: Final[tuple[Decimal, ...]] = (
    Decimal("0.50"),
    Decimal("0.60"),
    Decimal("0.70"),
    Decimal("0.80"),
    Decimal("0.90"),
)
_LOCKED_PROGRESS_LAG: Final[Decimal] = Decimal("0.20")
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass(slots=True, kw_only=True)
class PositionProtectionManager:
    """Move stop-loss forward in persistent steps as TP progress increases."""

    trade_mode: TradeMode
    position_repository: PositionRepository
    exchange_client: BaseExchangeClient
    position_refresh_seconds: float = _POSITION_REFRESH_SECONDS
    failure_retry_seconds: float = _FAILURE_RETRY_SECONDS
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _cached_position: Position | None = field(default=None, init=False, repr=False)
    _last_refresh_monotonic: float = field(default=0.0, init=False, repr=False)
    _retry_after_monotonic: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate the bounded repository refresh cadence."""
        if self.position_refresh_seconds <= 0:
            raise ValueError("Position refresh interval must be greater than zero")

        if self.failure_retry_seconds <= 0:
            raise ValueError("Protection retry interval must be greater than zero")

    async def on_market_tick(self, *, ticker: Ticker) -> None:
        """Advance profit protection when a stream tick crosses a new step."""
        async with self._lock:
            if monotonic() < self._retry_after_monotonic:
                return

            position = await self._get_position(symbol=ticker.symbol)

            if position is None or position.take_profit is None:
                return

            progress = self._calculate_tp_progress(
                position=position,
                current_price=ticker.last_price,
            )
            step = self._resolve_step(progress=progress)

            if step <= position.protection_step:
                return

            locked_progress = _PROGRESS_THRESHOLDS[step - 1] - _LOCKED_PROGRESS_LAG
            replacement_stop = self._calculate_stop_loss(
                position=position,
                locked_progress=locked_progress,
            )

            position_with_client_id = position
            final_stop = replacement_stop
            if self.trade_mode is TradeMode.LIVE:
                try:
                    final_stop = await self._normalize_live_replacement_stop(
                        position=position,
                        raw_stop=replacement_stop,
                    )
                except VenueRuleValidationError:
                    self._retry_after_monotonic = (
                        monotonic() + self.failure_retry_seconds
                    )
                    _LOGGER.warning(
                        "Live stepped protection deferred because the replacement "
                        "stop is not currently venue-valid: symbol=%s side=%s "
                        "raw_stop=%s",
                        position.symbol,
                        position.side.value,
                        replacement_stop,
                    )
                    return
                if not self._is_tighter_stop(
                    position=position,
                    replacement_stop=final_stop,
                ):
                    return
                position_with_client_id = replace(
                    position,
                    stop_loss=final_stop,
                    stop_loss_client_algo_id=Position.create_stop_loss_client_algo_id(),
                )
                await self.position_repository.update(
                    position=position_with_client_id,
                )
                self._cached_position = position_with_client_id

                try:
                    await self.exchange_client.ensure_stop_loss_order(
                        symbol=position_with_client_id.symbol,
                        side=self._closing_side(position_with_client_id.side),
                        quantity=position_with_client_id.quantity,
                        stop_loss=final_stop,
                        client_algo_id=(
                            position_with_client_id.stop_loss_client_algo_id
                        ),
                    )
                except Exception:
                    self._retry_after_monotonic = (
                        monotonic() + self.failure_retry_seconds
                    )
                    raise
            elif not self._is_tighter_stop(
                position=position,
                replacement_stop=final_stop,
            ):
                return

            protected_position = replace(
                position_with_client_id
                if self.trade_mode is TradeMode.LIVE
                else position,
                current_price=ticker.last_price,
                stop_loss=final_stop,
                protection_step=step,
                updated_at=ticker.timestamp,
            )
            await self.position_repository.update(position=protected_position)
            self._cached_position = protected_position
            _LOGGER.info(
                "Position profit protection advanced: mode=%s symbol=%s side=%s "
                "step=%d tp_progress=%.2f%% locked_progress=%.2f%% stop_loss=%s",
                self.trade_mode.value,
                position.symbol,
                position.side.value,
                step,
                progress * Decimal("100"),
                locked_progress * Decimal("100"),
                final_stop,
            )

    async def _normalize_live_replacement_stop(
        self,
        *,
        position: Position,
        raw_stop: Decimal,
    ) -> Decimal:
        """Return the final venue trigger before a stepped STOP mutation.

        The same ``ExchangeSymbolRules`` operation used by initial protection is
        deliberately reused here so durable and exchange trigger prices share
        one PRICE_FILTER representation.
        """
        rules = await self.exchange_client.get_market_entry_rules(
            symbol=position.symbol,
        )
        mark_price = await self.exchange_client.get_mark_price(symbol=position.symbol)
        return rules.normalize_protection_trigger(
            raw_trigger_price=raw_stop,
            position_side=position.side,
            order_type=OrderType.STOP_MARKET,
            mark_price=mark_price,
        )

    async def _get_position(self, *, symbol: str) -> Position | None:
        """Refresh the active position at a bounded cadence."""
        now = monotonic()
        cached = self._cached_position

        if (
            now - self._last_refresh_monotonic < self.position_refresh_seconds
            and cached is not None
            and cached.symbol.upper() == symbol.upper()
        ):
            return cached

        position = await self.position_repository.get_by_symbol(symbol=symbol)
        self._cached_position = position
        self._last_refresh_monotonic = now
        return position

    @staticmethod
    def _calculate_tp_progress(
        *,
        position: Position,
        current_price: Decimal,
    ) -> Decimal:
        """Return favorable price movement as a ratio of the TP distance."""
        take_profit = position.take_profit

        if take_profit is None:
            return _DECIMAL_ZERO

        target_distance = abs(take_profit - position.entry_price)

        if target_distance <= _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        favorable_move = (
            current_price - position.entry_price
            if position.side is PositionSide.LONG
            else position.entry_price - current_price
        )
        return max(favorable_move / target_distance, _DECIMAL_ZERO)

    @staticmethod
    def _resolve_step(*, progress: Decimal) -> int:
        """Return the highest crossed step number."""
        return sum(progress >= threshold for threshold in _PROGRESS_THRESHOLDS)

    @staticmethod
    def _calculate_stop_loss(
        *,
        position: Position,
        locked_progress: Decimal,
    ) -> Decimal:
        """Calculate the profit-lock price for a long or short position."""
        take_profit = position.take_profit

        if take_profit is None:
            raise ValueError("Profit protection requires a take-profit price")

        locked_distance = abs(take_profit - position.entry_price) * locked_progress

        if position.side is PositionSide.LONG:
            return position.entry_price + locked_distance

        return position.entry_price - locked_distance

    @staticmethod
    def _is_tighter_stop(
        *,
        position: Position,
        replacement_stop: Decimal,
    ) -> bool:
        """Return whether a replacement can only increase protected profit."""
        current_stop = position.stop_loss

        if current_stop is None:
            return True

        if position.side is PositionSide.LONG:
            return replacement_stop > current_stop

        return replacement_stop < current_stop

    @staticmethod
    def _closing_side(side: PositionSide) -> OrderSide:
        """Return the reduce-only order side for an active position."""
        return OrderSide.SELL if side is PositionSide.LONG else OrderSide.BUY
