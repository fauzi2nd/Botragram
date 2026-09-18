"""Event-driven stepped profit protection for active positions."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from typing import Final, Protocol

from botragram.engine.risk_engine import (
    DEFAULT_BREAKEVEN_FEE_BUFFER,
    DEFAULT_BREAKEVEN_ROI_THRESHOLD,
    LOCKED_PROGRESS_LAG,
    PROGRESS_THRESHOLDS,
    RiskEngine,
)
from botragram.enums import (
    NotificationType,
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
from botragram.models import Notification, Order, Position, Ticker
from botragram.repositories import PositionRepository
from botragram.services.live_position_lifecycle_coordinator import (
    LivePositionLifecycleCoordinator,
)
from botragram.telegram.messages import get_partial_tp_message

__all__ = [
    "PartialTpNotificationPublisher",
    "PositionProtectionManager",
]


class PartialTpNotificationPublisher(Protocol):
    """Publish arbitrary notifications to notification channels."""

    async def publish(self, *, notification: Notification) -> None: ...


_POSITION_REFRESH_SECONDS: Final[float] = 1.0
_FAILURE_RETRY_SECONDS: Final[float] = 5.0
_PENDING_RECONCILIATION_ATTEMPTS: Final[int] = 2
_PENDING_RECONCILIATION_DELAY_SECONDS: Final[float] = 0.05
_BREAKEVEN_ROI_THRESHOLD: Final[Decimal] = DEFAULT_BREAKEVEN_ROI_THRESHOLD
_BREAKEVEN_FEE_BUFFER: Final[Decimal] = DEFAULT_BREAKEVEN_FEE_BUFFER
_PROGRESS_THRESHOLDS: Final[tuple[Decimal, ...]] = PROGRESS_THRESHOLDS
_LOCKED_PROGRESS_LAG: Final[Decimal] = LOCKED_PROGRESS_LAG
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_TERMINAL_CANCELLED_STATUSES: Final[frozenset[OrderStatus]] = frozenset(
    {
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.EXPIRED_IN_MATCH,
    }
)
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass(slots=True, kw_only=True)
class PositionProtectionManager:
    """Move stop-loss forward in persistent steps as TP progress increases."""

    trade_mode: TradeMode
    position_repository: PositionRepository
    exchange_client: BaseExchangeClient
    position_refresh_seconds: float = _POSITION_REFRESH_SECONDS
    failure_retry_seconds: float = _FAILURE_RETRY_SECONDS
    breakeven_roi_threshold: Decimal = _BREAKEVEN_ROI_THRESHOLD
    breakeven_fee_buffer: Decimal = _BREAKEVEN_FEE_BUFFER
    partial_tp_enabled: bool = False
    partial_tp_ratio: Decimal = Decimal("0.50")
    partial_tp_trigger_progress: Decimal = Decimal("0.50")
    lifecycle_coordinator: LivePositionLifecycleCoordinator = field(
        default_factory=LivePositionLifecycleCoordinator,
    )
    notification_publisher: PartialTpNotificationPublisher | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _cached_position: Position | None = field(default=None, init=False, repr=False)
    _cached_position_version: int = field(default=0, init=False, repr=False)
    _last_refresh_monotonic: float = field(default=0.0, init=False, repr=False)
    _retry_after_monotonic: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate the bounded repository refresh cadence and thresholds."""
        if self.position_refresh_seconds <= 0:
            raise ValueError("Position refresh interval must be greater than zero")

        if self.failure_retry_seconds <= 0:
            raise ValueError("Protection retry interval must be greater than zero")

        if self.breakeven_roi_threshold <= 0:
            raise ValueError("Breakeven ROI threshold must be greater than zero")

        if self.breakeven_fee_buffer < 0:
            raise ValueError("Breakeven fee buffer must be non-negative")

        if not (_DECIMAL_ZERO < self.partial_tp_ratio < Decimal("1")):
            raise ValueError("Partial TP ratio must be between 0 and 1 exclusive")

        if not (_DECIMAL_ZERO < self.partial_tp_trigger_progress < Decimal("1")):
            raise ValueError(
                "Partial TP trigger progress must be between 0 and 1 exclusive"
            )

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
                and position.pending_partial_tp_client_order_id is not None
            ):
                await self._resume_pending_partial_take_profit(
                    position=position,
                    ticker=ticker,
                )
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

            if (
                self.partial_tp_enabled
                and not position.partial_tp_executed
                and progress >= self.partial_tp_trigger_progress
            ):
                position = await self._execute_partial_take_profit(
                    position=position,
                    ticker=ticker,
                    progress=progress,
                )

            roi = self._calculate_roi(
                position=position,
                current_price=ticker.last_price,
            )
            step = self._resolve_step(
                progress=progress,
                roi=roi,
                breakeven_roi_threshold=self.breakeven_roi_threshold,
            )

            if step <= position.protection_step:
                return

            try:
                replacement_stop = self._calculate_stop_loss(
                    position=position,
                    step=step,
                    breakeven_fee_buffer=self.breakeven_fee_buffer,
                )
            except ValueError as err:
                _LOGGER.warning(
                    "Invalid protection geometry for %s at step %s: %s. "
                    "Retaining current protection.",
                    position.symbol,
                    step,
                    err,
                )
                self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
                return

            new_step = step
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

                is_same_stop = (
                    position.stop_loss is not None and final_stop == position.stop_loss
                )
                if is_same_stop and new_step > position.protection_step:
                    protected_position = replace(
                        position,
                        protection_step=new_step,
                        updated_at=ticker.timestamp,
                    )
                elif not self._is_tighter_stop(
                    position=position,
                    replacement_stop=final_stop,
                ):
                    return
                else:
                    pending = replace(
                        position,
                        pending_stop_loss=final_stop,
                        pending_stop_loss_client_algo_id=(
                            Position.create_stop_loss_client_algo_id()
                        ),
                        pending_protection_step=new_step,
                    )
                    await self.position_repository.update(position=pending)
                    self._cached_position = pending

                    try:
                        replacement_submitted = (
                            await self._submit_pending_stop_replacement(
                                position=pending
                            )
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
                is_same_stop = (
                    position.stop_loss is not None and final_stop == position.stop_loss
                )
                if is_same_stop and new_step > position.protection_step:
                    protected_position = replace(
                        position,
                        current_price=ticker.last_price,
                        protection_step=new_step,
                        updated_at=ticker.timestamp,
                    )
                elif not self._is_tighter_stop(
                    position=position,
                    replacement_stop=final_stop,
                ):
                    return
                else:
                    protected_position = replace(
                        position,
                        current_price=ticker.last_price,
                        stop_loss=final_stop,
                        protection_step=new_step,
                        updated_at=ticker.timestamp,
                    )

            await self.position_repository.update(position=protected_position)
            self._cached_position = protected_position
            locked_progress = (
                _PROGRESS_THRESHOLDS[new_step - 2] - _LOCKED_PROGRESS_LAG
                if new_step >= 2
                else _DECIMAL_ZERO
            )
            _LOGGER.info(
                "Position profit protection advanced: mode=%s symbol=%s side=%s "
                "step=%d tp_progress=%.2f%% locked_progress=%.2f%% stop_loss=%s",
                self.trade_mode.value,
                position.symbol,
                position.side.value,
                new_step,
                progress * Decimal("100"),
                locked_progress * Decimal("100"),
                final_stop,
            )

    async def _execute_partial_take_profit(
        self,
        *,
        position: Position,
        ticker: Ticker,
        progress: Decimal,
    ) -> Position:
        """Execute a partial take-profit exit and advance stop-loss to breakeven."""
        del progress
        raw_close_qty = position.quantity * self.partial_tp_ratio
        closing_side = self._closing_side(position.side)

        if self.trade_mode is TradeMode.LIVE:
            try:
                rules = await self.exchange_client.get_market_entry_rules(
                    symbol=position.symbol,
                )
                close_qty = (
                    raw_close_qty // rules.market_quantity_step
                ) * rules.market_quantity_step
            except Exception as err:
                _LOGGER.warning(
                    "Failed to fetch market entry rules for partial TP on %s: %s",
                    position.symbol,
                    err,
                )
                return position

            remaining_qty = position.quantity - close_qty
            if close_qty <= _DECIMAL_ZERO or remaining_qty < rules.market_min_quantity:
                _LOGGER.warning(
                    "Partial TP skipped: quantity %s cannot split with ratio %s "
                    "(min_qty=%s, step=%s). Marking partial TP completed for "
                    "position %s.",
                    position.quantity,
                    self.partial_tp_ratio,
                    rules.market_min_quantity,
                    rules.market_quantity_step,
                    position.symbol,
                )
                updated_position = replace(
                    position,
                    partial_tp_executed=True,
                    updated_at=ticker.timestamp,
                )
                await self.position_repository.update(position=updated_position)
                self._cached_position = updated_position
                return updated_position

            client_order_id = Position.create_partial_tp_client_order_id()
            intent_pos = replace(
                position,
                pending_partial_tp_client_order_id=client_order_id,
                pending_partial_tp_quantity=close_qty,
                updated_at=ticker.timestamp,
            )
            await self.position_repository.update(position=intent_pos)
            self._cached_position = intent_pos
            position = intent_pos

            try:
                ptp_order = await self.exchange_client.create_reduce_only_market_order(
                    symbol=position.symbol,
                    side=closing_side,
                    quantity=close_qty,
                    client_order_id=client_order_id,
                )
            except Exception as err:
                _LOGGER.error(
                    "Failed to execute LIVE partial TP order for %s: %s",
                    position.symbol,
                    err,
                )
                self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
                return position

            return await self._handle_live_partial_tp_order_outcome(
                position=position,
                ptp_order=ptp_order,
                client_order_id=client_order_id,
                requested_qty=close_qty,
                ticker=ticker,
            )

        close_qty = (position.quantity * self.partial_tp_ratio).normalize()
        remaining_qty = position.quantity - close_qty
        be_stop = self._calculate_stop_loss(
            position=position,
            step=1,
            breakeven_fee_buffer=self.breakeven_fee_buffer,
        )
        new_stop = (
            be_stop
            if self._is_tighter_stop(position=position, replacement_stop=be_stop)
            else position.stop_loss
        )
        updated_position = replace(
            position,
            quantity=remaining_qty,
            current_price=ticker.last_price,
            stop_loss=new_stop,
            protection_step=max(position.protection_step, 1),
            partial_tp_executed=True,
            updated_at=ticker.timestamp,
        )
        await self.position_repository.update(position=updated_position)
        self._cached_position = updated_position

        _LOGGER.info(
            "Partial take-profit executed: mode=%s symbol=%s closed_qty=%s "
            "remaining_qty=%s stop_loss=%s",
            self.trade_mode.value,
            position.symbol,
            close_qty,
            remaining_qty,
            updated_position.stop_loss,
        )

        await self._publish_partial_tp_notification(
            position=position,
            close_qty=close_qty,
            remaining_qty=remaining_qty,
            ticker=ticker,
            stop_loss=updated_position.stop_loss,
        )

        return updated_position

    async def _resume_pending_partial_take_profit(
        self,
        *,
        position: Position,
        ticker: Ticker,
    ) -> Position:
        """Reconcile and resume one durable pending LIVE partial TP mutation."""
        client_order_id = position.pending_partial_tp_client_order_id
        if client_order_id is None:
            return position

        requested_qty = position.pending_partial_tp_quantity or position.quantity
        last_unknown: ExchangeOrderOutcomeUnknownError | None = None
        ptp_order: Order | None = None

        for attempt in range(_PENDING_RECONCILIATION_ATTEMPTS):
            try:
                ptp_order = await self.exchange_client.get_order_by_client_order_id(
                    symbol=position.symbol,
                    client_order_id=client_order_id,
                )
                last_unknown = None
                break
            except ExchangeOrderNotFoundError:
                last_unknown = None
                if attempt + 1 < _PENDING_RECONCILIATION_ATTEMPTS:
                    await asyncio.sleep(_PENDING_RECONCILIATION_DELAY_SECONDS)
            except ExchangeOrderOutcomeUnknownError as error:
                last_unknown = error
                if attempt + 1 < _PENDING_RECONCILIATION_ATTEMPTS:
                    await asyncio.sleep(_PENDING_RECONCILIATION_DELAY_SECONDS)
            except Exception as err:
                _LOGGER.warning(
                    "Failed to query order %s for %s: %s",
                    client_order_id,
                    position.symbol,
                    err,
                )
                self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
                return position

        if ptp_order is None:
            if last_unknown is not None:
                _LOGGER.warning(
                    "Order %s for %s remains unverifiable after %d attempts: %s",
                    client_order_id,
                    position.symbol,
                    _PENDING_RECONCILIATION_ATTEMPTS,
                    last_unknown,
                )
                self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
                return position

            # Order not found after bounded attempts -> Inspect exchange positions
            try:
                exchange_positions = await self.exchange_client.get_positions(
                    symbol=position.symbol,
                )
            except Exception as pos_err:
                _LOGGER.warning(
                    "Order %s not found on exchange and position check failed: %s. "
                    "Retaining pending intent for retry.",
                    client_order_id,
                    pos_err,
                )
                self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
                return position

            matching = [
                p
                for p in exchange_positions
                if p.symbol.upper() == position.symbol.upper()
                and p.side == position.side
            ]
            if matching:
                exchange_pos = matching[0]
                if exchange_pos.quantity < position.quantity:
                    executed_qty = position.quantity - exchange_pos.quantity
                    if (
                        _DECIMAL_ZERO < executed_qty <= requested_qty
                        and executed_qty <= position.quantity
                    ):
                        _LOGGER.info(
                            "Reconciled executed partial TP from position reduction: "
                            "symbol=%s executed=%s new_qty=%s",
                            position.symbol,
                            executed_qty,
                            exchange_pos.quantity,
                        )
                        return await self._transition_after_partial_fill(
                            position=position,
                            executed_qty=executed_qty,
                            ptp_order_id=f"reconciled-{client_order_id}",
                            ticker=ticker,
                        )
                elif exchange_pos.quantity == position.quantity:
                    cleared = replace(
                        position,
                        pending_partial_tp_client_order_id=None,
                        pending_partial_tp_quantity=None,
                        updated_at=ticker.timestamp,
                    )
                    await self.position_repository.update(position=cleared)
                    self._cached_position = cleared
                    _LOGGER.info(
                        "Pending partial TP order %s not found and position untouched; "
                        "cleared intent safely for %s",
                        client_order_id,
                        position.symbol,
                    )
                    return cleared

            self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
            return position

        return await self._handle_live_partial_tp_order_outcome(
            position=position,
            ptp_order=ptp_order,
            client_order_id=client_order_id,
            requested_qty=requested_qty,
            ticker=ticker,
        )

    async def _handle_live_partial_tp_order_outcome(
        self,
        *,
        position: Position,
        ptp_order: Order,
        client_order_id: str,
        requested_qty: Decimal,
        ticker: Ticker,
    ) -> Position:
        """Process partial TP order outcome under strict terminal state rules."""
        if ptp_order.status in _TERMINAL_CANCELLED_STATUSES:
            if ptp_order.executed_quantity <= _DECIMAL_ZERO:
                _LOGGER.warning(
                    "LIVE partial TP order %s for %s was terminal (%s) with zero fill; "
                    "clearing durable intent.",
                    ptp_order.order_id,
                    position.symbol,
                    ptp_order.status.value,
                )
                cleared = replace(
                    position,
                    pending_partial_tp_client_order_id=None,
                    pending_partial_tp_quantity=None,
                    updated_at=ticker.timestamp,
                )
                await self.position_repository.update(position=cleared)
                self._cached_position = cleared
                return cleared

            return await self._process_verified_partial_fill(
                position=position,
                ptp_order=ptp_order,
                requested_qty=requested_qty,
                ticker=ticker,
            )

        if ptp_order.status is OrderStatus.FILLED:
            return await self._process_verified_partial_fill(
                position=position,
                ptp_order=ptp_order,
                requested_qty=requested_qty,
                ticker=ticker,
            )

        if ptp_order.status is OrderStatus.PARTIALLY_FILLED:
            _LOGGER.warning(
                "LIVE partial TP order %s for %s is PARTIALLY_FILLED "
                "(executed=%s/%s). Cancelling unfilled remainder.",
                ptp_order.order_id,
                position.symbol,
                ptp_order.executed_quantity,
                requested_qty,
            )
            try:
                await self.exchange_client.cancel_order(
                    symbol=position.symbol,
                    order_id=ptp_order.order_id,
                )
            except Exception as cancel_err:
                _LOGGER.warning(
                    "Failed to cancel remaining quantity of order %s for %s: %s. "
                    "Retaining durable intent.",
                    ptp_order.order_id,
                    position.symbol,
                    cancel_err,
                )
                self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
                return position

            try:
                post_cancel_order = (
                    await self.exchange_client.get_order_by_client_order_id(
                        symbol=position.symbol,
                        client_order_id=client_order_id,
                    )
                )
            except Exception as lookup_err:
                _LOGGER.warning(
                    "Failed to query order %s for %s after cancellation: %s. "
                    "Retaining durable intent.",
                    client_order_id,
                    position.symbol,
                    lookup_err,
                )
                self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
                return position

            if post_cancel_order.status is OrderStatus.FILLED:
                _LOGGER.info(
                    "LIVE partial TP order %s filled during cancel request "
                    "(cancel race). Processing full fill.",
                    post_cancel_order.order_id,
                )
                return await self._process_verified_partial_fill(
                    position=position,
                    ptp_order=post_cancel_order,
                    requested_qty=requested_qty,
                    ticker=ticker,
                )

            if post_cancel_order.status in _TERMINAL_CANCELLED_STATUSES:
                if post_cancel_order.executed_quantity <= _DECIMAL_ZERO:
                    cleared = replace(
                        position,
                        pending_partial_tp_client_order_id=None,
                        pending_partial_tp_quantity=None,
                        updated_at=ticker.timestamp,
                    )
                    await self.position_repository.update(position=cleared)
                    self._cached_position = cleared
                    return cleared

                return await self._process_verified_partial_fill(
                    position=position,
                    ptp_order=post_cancel_order,
                    requested_qty=requested_qty,
                    ticker=ticker,
                )

            # Post-cancel order is still non-terminal
            # (PARTIALLY_FILLED, NEW, TRIGGERING, etc.)
            _LOGGER.warning(
                "LIVE partial TP order %s remains in non-terminal status (%s) "
                "after cancellation. Retaining durable intent.",
                post_cancel_order.order_id,
                post_cancel_order.status.value,
            )
            self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
            return position

        if ptp_order.status in (OrderStatus.NEW, OrderStatus.TRIGGERING):
            _LOGGER.info(
                "LIVE partial TP order %s for %s is %s; awaiting fill/terminal status.",
                ptp_order.order_id,
                position.symbol,
                ptp_order.status.value,
            )
            return position

        _LOGGER.error(
            "LIVE partial TP order %s for %s has unrecognized/non-terminal status %s. "
            "Failing closed, retaining durable intent.",
            ptp_order.order_id,
            position.symbol,
            ptp_order.status.value,
        )
        self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
        return position

    async def _process_verified_partial_fill(
        self,
        *,
        position: Position,
        ptp_order: Order,
        requested_qty: Decimal,
        ticker: Ticker,
    ) -> Position:
        """Validate strict executed quantity invariants before mutating position."""
        executed_qty = ptp_order.executed_quantity
        if (
            executed_qty <= _DECIMAL_ZERO
            or executed_qty > requested_qty
            or executed_qty > position.quantity
        ):
            _LOGGER.error(
                "Executed quantity %s violates invariants for %s "
                "(req=%s, pos_qty=%s). Failing closed, retaining intent.",
                executed_qty,
                position.symbol,
                requested_qty,
                position.quantity,
            )
            self._retry_after_monotonic = monotonic() + self.failure_retry_seconds
            return position

        return await self._transition_after_partial_fill(
            position=position,
            executed_qty=executed_qty,
            ptp_order_id=ptp_order.order_id,
            ticker=ticker,
        )

    async def _transition_after_partial_fill(
        self,
        *,
        position: Position,
        executed_qty: Decimal,
        ptp_order_id: str,
        ticker: Ticker,
    ) -> Position:
        """Atomically deduct filled quantity and arm replacement stop."""
        if executed_qty <= _DECIMAL_ZERO or executed_qty > position.quantity:
            _LOGGER.error(
                "Invalid executed_qty %s for position %s (qty=%s)",
                executed_qty,
                position.symbol,
                position.quantity,
            )
            return position

        remaining_qty = position.quantity - executed_qty
        if remaining_qty < _DECIMAL_ZERO:
            _LOGGER.error(
                "Remaining quantity would be negative (%s - %s)",
                position.quantity,
                executed_qty,
            )
            return position

        try:
            be_stop = self._calculate_stop_loss(
                position=position,
                step=1,
                breakeven_fee_buffer=self.breakeven_fee_buffer,
            )
            try:
                final_stop = await self._normalize_live_replacement_stop(
                    position=position,
                    raw_stop=be_stop,
                )
            except VenueRuleValidationError:
                final_stop = be_stop

            new_stop = (
                final_stop
                if self._is_tighter_stop(position=position, replacement_stop=final_stop)
                else position.stop_loss
            )
        except ValueError as err:
            _LOGGER.warning(
                "Cannot calculate BE stop after partial TP for %s: %s. "
                "Retaining current verified stop.",
                position.symbol,
                err,
            )
            new_stop = position.stop_loss
        new_stop_id = Position.create_stop_loss_client_algo_id()

        pending_stop_pos = replace(
            position,
            quantity=remaining_qty,
            current_price=ticker.last_price,
            pending_stop_loss=new_stop,
            pending_stop_loss_client_algo_id=new_stop_id,
            pending_protection_step=max(position.protection_step, 1),
            partial_tp_executed=True,
            partial_tp_order_id=ptp_order_id,
            pending_partial_tp_client_order_id=None,
            pending_partial_tp_quantity=None,
            updated_at=ticker.timestamp,
        )
        await self.position_repository.update(position=pending_stop_pos)
        self._cached_position = pending_stop_pos

        _LOGGER.info(
            "LIVE partial TP fill verified: symbol=%s executed=%s remaining=%s "
            "order_id=%s. Armed pending stop=%s",
            position.symbol,
            executed_qty,
            remaining_qty,
            ptp_order_id,
            new_stop,
        )

        await self._publish_partial_tp_notification(
            position=position,
            close_qty=executed_qty,
            remaining_qty=remaining_qty,
            ticker=ticker,
            stop_loss=new_stop,
        )

        try:
            await self._complete_pending_stop_replacement(
                position=pending_stop_pos,
                timestamp=ticker.timestamp,
                current_price=ticker.last_price,
            )
            return self._cached_position or pending_stop_pos
        except Exception as err:
            _LOGGER.warning(
                "Stop replacement after partial TP failed for %s: %s. "
                "Previous stop remains active; pending stop queued.",
                position.symbol,
                err,
            )
            return pending_stop_pos

    async def _publish_partial_tp_notification(
        self,
        *,
        position: Position,
        close_qty: Decimal,
        remaining_qty: Decimal,
        ticker: Ticker,
        stop_loss: Decimal | None,
    ) -> None:
        """Publish partial TP notification safely."""
        if self.notification_publisher is None:
            return

        try:
            msg = get_partial_tp_message(
                position=position,
                closed_quantity=close_qty,
                remaining_quantity=remaining_qty,
                exit_price=ticker.last_price,
                new_stop_loss=stop_loss,
                mode=self.trade_mode.value.upper(),
            )
            await self.notification_publisher.publish(
                notification=Notification(
                    title=f"Partial TP Executed: {position.symbol}",
                    message=msg,
                    level=NotificationType.INFO,
                    created_at=datetime.now(UTC),
                )
            )
        except Exception:
            _LOGGER.exception(
                "Failed to deliver partial TP notification for %s",
                position.symbol,
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
        _LOGGER.debug(
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
        reference_price = await self.exchange_client.get_reference_price(
            symbol=position.symbol,
        )
        return rules.normalize_protection_trigger(
            raw_trigger_price=raw_stop,
            position_side=position.side,
            order_type=OrderType.STOP_MARKET,
            reference_price=reference_price,
        )

    async def _get_position(self, *, symbol: str) -> Position | None:
        """Refresh the active position at a bounded cadence."""
        now = monotonic()
        cached = self._cached_position
        position_version = self.lifecycle_coordinator.get_position_version(
            symbol=symbol,
        )

        if (
            now - self._last_refresh_monotonic < self.position_refresh_seconds
            and cached is not None
            and cached.symbol.upper() == symbol.upper()
            and self._cached_position_version == position_version
        ):
            return cached

        position = await self.position_repository.get_by_symbol(symbol=symbol)
        self._cached_position = position
        self._cached_position_version = position_version
        self._last_refresh_monotonic = now
        return position

    @staticmethod
    def _calculate_tp_progress(
        *,
        position: Position,
        current_price: Decimal,
    ) -> Decimal:
        """Return favorable price movement as a ratio of the TP distance."""
        return RiskEngine.calculate_tp_progress(
            position=position,
            current_price=current_price,
        )

    @staticmethod
    def _calculate_roi(
        *,
        position: Position,
        current_price: Decimal,
    ) -> Decimal:
        """Return return-on-equity (ROI) ratio based on position leverage."""
        return RiskEngine.calculate_position_roi(
            position=position,
            current_price=current_price,
        )

    @classmethod
    def resolve_step(
        cls,
        *,
        progress: Decimal,
        roi: Decimal,
        breakeven_roi_threshold: Decimal = _BREAKEVEN_ROI_THRESHOLD,
    ) -> int:
        """Return the highest crossed protection step number."""
        return RiskEngine.resolve_target_protection_step(
            progress=progress,
            roi=roi,
            breakeven_roi_threshold=breakeven_roi_threshold,
        )

    _resolve_step = resolve_step

    @classmethod
    def _calculate_stop_loss(
        cls,
        *,
        position: Position,
        step: int,
        breakeven_fee_buffer: Decimal = _BREAKEVEN_FEE_BUFFER,
    ) -> Decimal:
        """Calculate the profit-lock price for a specific protection step."""
        return RiskEngine.calculate_stepped_stop_loss(
            position=position,
            step=step,
            breakeven_fee_buffer=breakeven_fee_buffer,
        )

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
