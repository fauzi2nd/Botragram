"""Event-driven stepped profit protection for active positions."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from time import monotonic
from typing import Final

from botragram.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TradeMode,
)
from botragram.exceptions import (
    ExchangeOrderImmediateTriggerRejectedError,
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    VenueRuleValidationError,
)
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Order, Position, Ticker
from botragram.repositories import PositionRepository
from botragram.services.live_position_lifecycle_coordinator import (
    LivePositionLifecycleCoordinator,
)

__all__ = ["PositionProtectionManager"]


_POSITION_REFRESH_SECONDS: Final[float] = 1.0
_FAILURE_RETRY_SECONDS: Final[float] = 5.0
_PENDING_RECONCILIATION_ATTEMPTS: Final[int] = 2
_PENDING_RECONCILIATION_DELAY_SECONDS: Final[float] = 0.05
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
    lifecycle_coordinator: LivePositionLifecycleCoordinator = field(
        default_factory=LivePositionLifecycleCoordinator,
    )
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
        async with self.lifecycle_coordinator.hold(symbol=ticker.symbol):
            await self._on_market_tick(ticker=ticker)

    async def _on_market_tick(self, *, ticker: Ticker) -> None:
        """Advance one protected position while it is lifecycle-owned."""
        async with self._lock:
            if monotonic() < self._retry_after_monotonic:
                return

            position = await self._get_position(symbol=ticker.symbol)
            if position is None or position.take_profit is None:
                return

            if (
                self.trade_mode is TradeMode.LIVE
                and position.pending_stop_loss_client_algo_id is not None
            ):
                await self._resume_pending_stop_replacement(
                    position=position,
                    timestamp=ticker.timestamp,
                    current_price=ticker.last_price,
                )
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
            final_stop = replacement_stop

            if self.trade_mode is TradeMode.LIVE:
                try:
                    final_stop = await self._normalize_live_replacement_stop(
                        position=position,
                        raw_stop=replacement_stop,
                    )
                except VenueRuleValidationError:
                    self._defer_live_replacement(
                        position=position,
                        raw_stop=replacement_stop,
                    )
                    return

                if not self._is_tighter_stop(
                    position=position,
                    replacement_stop=final_stop,
                ):
                    return

                pending = replace(
                    position,
                    pending_stop_loss=final_stop,
                    pending_stop_loss_client_algo_id=(
                        Position.create_stop_loss_client_algo_id()
                    ),
                    pending_protection_step=step,
                )
                await self.position_repository.update(position=pending)
                self._cached_position = pending

                try:
                    replacement_submitted = await self._submit_pending_stop_replacement(
                        position=pending
                    )
                except Exception:
                    self._retry_after_monotonic = (
                        monotonic() + self.failure_retry_seconds
                    )
                    raise

                if not replacement_submitted:
                    return

                protected_position = self._promote_pending_stop_replacement(
                    position=pending,
                    timestamp=ticker.timestamp,
                    current_price=ticker.last_price,
                )
            else:
                if not self._is_tighter_stop(
                    position=position,
                    replacement_stop=final_stop,
                ):
                    return
                protected_position = replace(
                    position,
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

    async def _resume_pending_stop_replacement(
        self,
        *,
        position: Position,
        timestamp: datetime,
        current_price: Decimal,
    ) -> None:
        """Resume or retire one durable pending LIVE STOP mutation."""
        pending_stop = position.pending_stop_loss
        pending_id = position.pending_stop_loss_client_algo_id
        if pending_stop is None or pending_id is None:
            raise RuntimeError("Pending LIVE STOP replacement is incomplete")

        existing = await self._get_pending_stop_replacement(position=position)
        if existing is not None:
            if existing.status in {
                OrderStatus.CANCELED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            }:
                await self._require_current_stop_after_terminal_pending(
                    position=position,
                )
                await self._clear_pending_stop_replacement(
                    position=position,
                    reason=f"terminal_{existing.status.value}",
                )
                return
            if existing.status is OrderStatus.FILLED:
                raise RuntimeError(
                    "Pending LIVE STOP is filled while managed position remains active"
                )
            if existing.status is not OrderStatus.NEW:
                raise RuntimeError("Pending LIVE STOP is neither active nor terminal")

            await self._complete_pending_stop_replacement(
                position=position,
                timestamp=timestamp,
                current_price=current_price,
            )
            return

        try:
            normalized_stop = await self._normalize_live_replacement_stop(
                position=position,
                raw_stop=pending_stop,
            )
        except VenueRuleValidationError:
            await self._clear_pending_stop_replacement(
                position=position,
                reason="not_found_and_venue_invalid",
            )
            return

        if normalized_stop != pending_stop:
            await self._clear_pending_stop_replacement(
                position=position,
                reason="not_found_and_normalization_changed",
            )
            return

        await self._complete_pending_stop_replacement(
            position=position,
            timestamp=timestamp,
            current_price=current_price,
        )

    async def _require_current_stop_after_terminal_pending(
        self,
        *,
        position: Position,
    ) -> None:
        """Prove the predecessor still protects an active position.

        A terminal pending replacement may have occurred before or after the
        predecessor was retired. Clearing its durable identity is safe only
        when the exact current identity remains an active, matching STOP.
        """
        current_id = position.stop_loss_client_algo_id
        current_stop = position.stop_loss
        if current_id is None or current_stop is None:
            raise RuntimeError(
                "Terminal pending LIVE STOP has no durable current protection"
            )

        try:
            current = await self.exchange_client.get_protection_order_by_client_id(
                symbol=position.symbol,
                client_id=current_id,
            )
        except ExchangeOrderNotFoundError as error:
            raise RuntimeError(
                "Current LIVE STOP is absent after terminal pending replacement"
            ) from error
        except ExchangeOrderOutcomeUnknownError as error:
            raise RuntimeError(
                "Current LIVE STOP is unverifiable after terminal pending replacement"
            ) from error

        expected_side = self._closing_side(position.side)
        if (
            current.client_order_id != current_id
            or current.symbol.upper() != position.symbol.upper()
            or current.side is not expected_side
            or current.order_type is not OrderType.STOP_MARKET
            or current.status is not OrderStatus.NEW
            or current.quantity != position.quantity
            or current.stop_price != current_stop
        ):
            raise RuntimeError(
                "Current LIVE STOP does not protect after terminal pending replacement"
            )

    async def _get_pending_stop_replacement(
        self,
        *,
        position: Position,
    ) -> Order | None:
        """Resolve a pending STOP solely through its exact durable identity."""
        pending_id = position.pending_stop_loss_client_algo_id
        pending_stop = position.pending_stop_loss
        if pending_id is None or pending_stop is None:
            raise RuntimeError("Pending LIVE STOP replacement is incomplete")

        last_unknown: ExchangeOrderOutcomeUnknownError | None = None
        for attempt in range(_PENDING_RECONCILIATION_ATTEMPTS):
            try:
                order = await self.exchange_client.get_protection_order_by_client_id(
                    symbol=position.symbol,
                    client_id=pending_id,
                )
            except ExchangeOrderNotFoundError:
                last_unknown = None
            except ExchangeOrderOutcomeUnknownError as error:
                last_unknown = error
            else:
                self._validate_pending_stop_replacement(
                    order=order,
                    position=position,
                )
                return order

            if attempt + 1 < _PENDING_RECONCILIATION_ATTEMPTS:
                await asyncio.sleep(_PENDING_RECONCILIATION_DELAY_SECONDS)

        if last_unknown is not None:
            raise RuntimeError(
                "Pending LIVE STOP identity remains unverifiable"
            ) from last_unknown

        return None

    async def _complete_pending_stop_replacement(
        self,
        *,
        position: Position,
        timestamp: datetime,
        current_price: Decimal,
    ) -> None:
        """Prove pending STOP ownership, retire predecessor, then promote."""
        try:
            replacement_submitted = await self._submit_pending_stop_replacement(
                position=position
            )
        except Exception:
            self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
            raise

        if not replacement_submitted:
            return

        protected = self._promote_pending_stop_replacement(
            position=position,
            timestamp=timestamp,
            current_price=current_price,
        )
        await self.position_repository.update(position=protected)
        self._cached_position = protected
        _LOGGER.info(
            "Pending LIVE stepped protection promoted: symbol=%s step=%d stop_loss=%s",
            protected.symbol,
            protected.protection_step,
            protected.stop_loss,
        )

    async def _clear_pending_stop_replacement(
        self,
        *,
        position: Position,
        reason: str,
    ) -> None:
        """Retire a proven-inactive pending intent while preserving current STOP."""
        cleared = replace(
            position,
            pending_stop_loss=None,
            pending_stop_loss_client_algo_id=None,
            pending_protection_step=0,
        )
        await self.position_repository.update(position=cleared)
        self._cached_position = cleared
        _LOGGER.info(
            "Pending LIVE stepped protection retired: symbol=%s reason=%s",
            cleared.symbol,
            reason,
        )

    @staticmethod
    def _validate_pending_stop_replacement(
        *,
        order: Order,
        position: Position,
    ) -> None:
        """Require exact durable identity and immutable pending STOP shape."""
        pending_id = position.pending_stop_loss_client_algo_id
        pending_stop = position.pending_stop_loss
        if pending_id is None or pending_stop is None:
            raise RuntimeError("Pending LIVE STOP replacement is incomplete")

        expected_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        if (
            order.client_order_id != pending_id
            or order.symbol.upper() != position.symbol.upper()
            or order.side is not expected_side
            or order.order_type is not OrderType.STOP_MARKET
            or order.quantity != position.quantity
            or order.stop_price != pending_stop
        ):
            raise RuntimeError(
                "Pending LIVE STOP does not match its durable replacement identity"
            )

    async def _submit_pending_stop_replacement(self, *, position: Position) -> bool:
        """Submit or reconcile the exact pending STOP and retire current STOP.

        Returns:
            ``True`` when the pending replacement is exchange-proven active.
            ``False`` when Binance explicitly rejects it as immediately
            triggering and the current durable STOP is still proven active.

        Raises:
            RuntimeError: If protection ownership cannot be proven.
        """
        pending_stop = position.pending_stop_loss
        pending_id = position.pending_stop_loss_client_algo_id
        if pending_stop is None or pending_id is None:
            raise RuntimeError("Pending LIVE STOP replacement is incomplete")

        try:
            order = await self.exchange_client.ensure_stop_loss_order(
                symbol=position.symbol,
                side=self._closing_side(position.side),
                quantity=position.quantity,
                stop_loss=pending_stop,
                client_algo_id=pending_id,
                previous_client_algo_id=position.stop_loss_client_algo_id,
            )
        except ExchangeOrderImmediateTriggerRejectedError:
            await self._require_current_stop_after_terminal_pending(position=position)
            await self._clear_pending_stop_replacement(
                position=position,
                reason="explicit_immediate_trigger_rejected",
            )
            return False

        if (
            order.client_order_id != pending_id
            or order.symbol.upper() != position.symbol.upper()
            or order.side is not self._closing_side(position.side)
            or order.order_type is not OrderType.STOP_MARKET
            or order.status is not OrderStatus.NEW
            or order.quantity != position.quantity
            or order.stop_price != pending_stop
        ):
            raise RuntimeError(
                "Exchange did not prove the exact pending LIVE STOP replacement"
            )

        return True

    @staticmethod
    def _promote_pending_stop_replacement(
        *,
        position: Position,
        timestamp: datetime,
        current_price: Decimal,
    ) -> Position:
        """Promote only an exchange-proven pending STOP into current durable state."""
        pending_stop = position.pending_stop_loss
        pending_id = position.pending_stop_loss_client_algo_id
        if pending_stop is None or pending_id is None:
            raise RuntimeError("Pending LIVE STOP replacement is incomplete")

        return replace(
            position,
            current_price=current_price,
            stop_loss=pending_stop,
            stop_loss_client_algo_id=pending_id,
            protection_step=position.pending_protection_step,
            pending_stop_loss=None,
            pending_stop_loss_client_algo_id=None,
            pending_protection_step=0,
            updated_at=timestamp,
        )

    def _defer_live_replacement(
        self,
        *,
        position: Position,
        raw_stop: Decimal,
    ) -> None:
        """Defer a replacement while preserving the currently verified STOP."""
        self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
        _LOGGER.warning(
            "Live stepped protection deferred because the replacement "
            "stop is not currently venue-valid: symbol=%s side=%s raw_stop=%s",
            position.symbol,
            position.side.value,
            raw_stop,
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
