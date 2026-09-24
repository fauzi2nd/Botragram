"""Recover natural LIVE exits and remove proven orphan protection."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Final, Protocol

from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SubmissionAttemptStatus,
)
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
)
from botragram.models import Order, Position, Trade
from botragram.repositories import (
    PositionRepository,
    SubmissionAttemptRepository,
)
from botragram.services.closed_position_lifecycle_service import (
    ClosedPositionLifecycleService,
)
from botragram.services.live_position_lifecycle_coordinator import (
    LivePositionLifecycleCoordinator,
)

__all__ = [
    "LiveNaturalExitRecoveryService",
]


_RECONCILIATION_ATTEMPTS: Final[int] = 3
_RECONCILIATION_DELAY_SECONDS: Final[float] = 0.5
_PORTFOLIO_STABILITY_ATTEMPTS: Final[int] = 3
_MANUAL_CLOSE_TRADE_LIMIT: Final[int] = 1000
_TERMINAL_PROTECTION_STATUSES: Final[frozenset[OrderStatus]] = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class LiveNaturalExitExchange(Protocol):
    """Expose the authoritative reads and exact orphan-cancel boundary."""

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Return authoritative non-zero positions."""
        ...

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return authoritative open conditional protection orders."""
        ...

    async def get_protection_order_history(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> Sequence[Order]:
        """Return bounded authoritative conditional-order history."""
        ...

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        """Return one conditional protection order by durable identity."""
        ...

    async def get_trades(
        self,
        *,
        symbol: str | None,
        limit: int,
    ) -> Sequence[Trade]:
        """Return bounded authoritative account fills."""
        ...

    async def get_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Return one standard order by exact exchange identity."""
        ...

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str | None = None,
        order_id: str | None = None,
    ) -> None:
        """Attempt one exact conditional protection cancellation."""
        ...


class LiveOperatorExitRecoveryState(Protocol):
    """Expose operator closes that still own exact exit reconciliation."""

    async def get_incomplete_attempts(self) -> Sequence[object]:
        """Return operator-exit attempts that must block natural cleanup."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveNaturalExitRecoveryService:
    """Reconcile zero-exposure exits before another LIVE entry can be allowed.

    The service cancels only protection identities already persisted on a stale
    local Position. Unknown orphan conditional orders always block. A DELETE is
    never retried; ambiguous outcomes are resolved with bounded GET-only reads.
    """

    exchange_client: LiveNaturalExitExchange
    position_repository: PositionRepository
    submission_attempt_repository: SubmissionAttemptRepository
    operator_exit_repository: LiveOperatorExitRecoveryState | None = None
    closed_lifecycle_service: ClosedPositionLifecycleService | None = None
    lifecycle_coordinator: LivePositionLifecycleCoordinator = field(
        default_factory=LivePositionLifecycleCoordinator,
    )

    async def reconcile(self) -> None:
        """Remove proven orphan protection and stale local positions."""
        async with self.lifecycle_coordinator.hold_portfolio():
            await self._reconcile_under_lock()

    async def _reconcile_under_lock(self) -> None:
        operator_repository = self.operator_exit_repository
        if (
            operator_repository is not None
            and await operator_repository.get_incomplete_attempts()
        ):
            raise RuntimeError(
                "Incomplete LIVE operator exit requires exact recovery before "
                "natural-exit reconciliation"
            )
        incomplete_attempts = tuple(
            await self.submission_attempt_repository.get_incomplete()
        )
        if incomplete_attempts:
            raise RuntimeError(
                "Incomplete LIVE submission requires lifecycle recovery before "
                "natural-exit reconciliation"
            )

        for attempt in range(_PORTFOLIO_STABILITY_ATTEMPTS):
            stored_positions = tuple(await self.position_repository.get_all())
            stored_by_symbol = {
                position.symbol.upper(): position for position in stored_positions
            }
            initial_positions = tuple(await self.exchange_client.get_positions())
            open_protections = tuple(
                await self.exchange_client.get_open_protection_orders()
            )
            observed_positions = tuple(await self.exchange_client.get_positions())
            if not self._portfolio_snapshots_match(
                initial_positions=initial_positions,
                observed_positions=observed_positions,
            ):
                await self._validate_known_portfolio_transition(
                    initial_positions=initial_positions,
                    observed_positions=observed_positions,
                    stored_by_symbol=stored_by_symbol,
                )
                if attempt + 1 < _PORTFOLIO_STABILITY_ATTEMPTS:
                    continue
                raise RuntimeError(
                    "LIVE portfolio did not stabilize during natural-exit "
                    "reconciliation"
                )

            active_symbols = {
                position.symbol.upper() for position in observed_positions
            }
            await self._reconcile_orphan_protections(
                open_protections=open_protections,
                active_symbols=active_symbols,
                stored_by_symbol=stored_by_symbol,
            )
            final_protections = tuple(
                await self.exchange_client.get_open_protection_orders()
            )
            remaining_orphans = tuple(
                order
                for order in final_protections
                if order.symbol.upper() not in active_symbols
            )
            if remaining_orphans:
                refreshed_positions = tuple(await self.exchange_client.get_positions())
                if not self._portfolio_snapshots_match(
                    initial_positions=observed_positions,
                    observed_positions=refreshed_positions,
                ):
                    await self._validate_known_portfolio_transition(
                        initial_positions=observed_positions,
                        observed_positions=refreshed_positions,
                        stored_by_symbol=stored_by_symbol,
                    )
                    if attempt + 1 < _PORTFOLIO_STABILITY_ATTEMPTS:
                        continue
                    raise RuntimeError(
                        "LIVE portfolio did not stabilize during natural-exit "
                        "reconciliation"
                    )
                raise RuntimeError(
                    "LIVE orphan protection remains after reconciliation: "
                    f"count={len(remaining_orphans)}"
                )

            await self._delete_stale_positions(
                stored_positions=stored_positions,
                active_symbols=active_symbols,
            )
            settled_positions = tuple(await self.exchange_client.get_positions())
            if self._portfolio_snapshots_match(
                initial_positions=observed_positions,
                observed_positions=settled_positions,
            ):
                await self._reconcile_pending_lifecycles_best_effort()
                return
            await self._validate_known_portfolio_transition(
                initial_positions=observed_positions,
                observed_positions=settled_positions,
                stored_by_symbol={
                    position.symbol.upper(): position
                    for position in await self.position_repository.get_all()
                },
            )
            if attempt + 1 >= _PORTFOLIO_STABILITY_ATTEMPTS:
                raise RuntimeError(
                    "LIVE portfolio did not stabilize during natural-exit "
                    "reconciliation"
                )

    async def _reconcile_orphan_protections(
        self,
        *,
        open_protections: tuple[Order, ...],
        active_symbols: set[str],
        stored_by_symbol: dict[str, Position],
    ) -> None:
        """Cancel exact durable orphan legs only after a stable zero-exposure read."""
        orphan_groups: dict[str, list[Order]] = {}
        for order in open_protections:
            symbol = order.symbol.upper()
            if symbol not in active_symbols:
                orphan_groups.setdefault(symbol, []).append(order)
        for symbol in sorted(orphan_groups):
            stored_position = stored_by_symbol.get(symbol)
            orders = tuple(orphan_groups[symbol])
            if stored_position is None:
                if all(
                    (
                        Position.is_generated_stop_loss_client_algo_id(
                            order.client_order_id
                        )
                        or Position.is_generated_take_profit_client_algo_id(
                            order.client_order_id
                        )
                    )
                    for order in orders
                    if order.client_order_id is not None
                ) and all(order.client_order_id is not None for order in orders):
                    _LOGGER.warning(
                        "LIVE orphan protection belongs to Botragram but has no "
                        "local position; canceling orphaned bot protection to "
                        "prevent naked exposure: symbol=%s count=%d",
                        symbol,
                        len(orders),
                    )
                    for order in sorted(
                        orders,
                        key=lambda candidate: (
                            candidate.order_type.value,
                            candidate.client_order_id or "",
                        ),
                    ):
                        await self._cancel_and_reconcile(order=order)
                    continue
                raise RuntimeError(
                    "LIVE orphan protection has no durable position identity: "
                    f"symbol={symbol}"
                )
            for order in orders:
                self._validate_owned_orphan(order=order, position=stored_position)
            for order in sorted(
                orders,
                key=lambda candidate: (
                    candidate.order_type.value,
                    candidate.client_order_id or "",
                ),
            ):
                await self._cancel_and_reconcile(order=order)

    async def _delete_stale_positions(
        self,
        *,
        stored_positions: tuple[Position, ...],
        active_symbols: set[str],
    ) -> None:
        """Delete only durable positions with repeatedly proven zero exposure."""
        for position in stored_positions:
            if position.symbol.upper() in active_symbols:
                continue
            async with self.lifecycle_coordinator.hold(symbol=position.symbol):
                filled_exit_orders = (
                    await self._reconcile_persisted_protection_before_delete(
                        position=position,
                    )
                )
                if await self.exchange_client.get_positions(symbol=position.symbol):
                    raise RuntimeError(
                        "LIVE exposure reappeared before durable position deletion: "
                        f"symbol={position.symbol}"
                    )
                remaining = tuple(
                    await self.exchange_client.get_open_protection_orders(
                        symbol=position.symbol,
                    )
                )
                if remaining:
                    raise RuntimeError(
                        "LIVE protection remains before durable position deletion: "
                        f"symbol={position.symbol} count={len(remaining)}"
                    )
                lifecycle_id = await self._stage_closed_lifecycle(
                    position=position,
                    filled_exit_orders=filled_exit_orders,
                )
                await self.position_repository.delete(symbol=position.symbol)
                self.lifecycle_coordinator.record_position_deletion(
                    symbol=position.symbol,
                )
                if lifecycle_id is not None:
                    await self._complete_closed_lifecycle_best_effort(
                        entry_client_order_id=lifecycle_id,
                    )
            _LOGGER.info(
                "LIVE exit lifecycle reconciled: symbol=%s entry_client_order_id=%s",
                position.symbol,
                position.entry_client_order_id,
            )

    async def _reconcile_pending_lifecycles_best_effort(self) -> None:
        """Retry durable financial enrichment without blocking safety recovery."""
        service = self.closed_lifecycle_service
        if service is not None:
            await service.reconcile_pending_best_effort()

    async def _stage_closed_lifecycle(
        self,
        *,
        position: Position,
        filled_exit_orders: tuple[Order, ...],
    ) -> str | None:
        """Require durable ownership before deleting the local position identity."""
        service = self.closed_lifecycle_service
        entry_identity = position.entry_client_order_id
        if service is None or entry_identity is None:
            return None
        if await service.has_durable_ownership(
            entry_client_order_id=entry_identity,
        ):
            return entry_identity
        attempt = await self.submission_attempt_repository.get_by_client_order_id(
            client_order_id=entry_identity,
        )
        if (
            attempt is None
            or attempt.status is not SubmissionAttemptStatus.COMPLETED
            or attempt.exchange_order_id is None
        ):
            raise RuntimeError(
                "Natural exit cannot delete an unstaged lifecycle identity"
            )
        if len(filled_exit_orders) > 1:
            raise RuntimeError(
                "Natural exit requires exactly one authoritative FILLED exit"
            )
        threshold_time = min(attempt.created_at, position.opened_at)
        provenance = ClosedPositionProvenance.PROTECTION_ORDER
        close_reason: ClosedPositionReason
        if filled_exit_orders:
            exit_order = filled_exit_orders[0]
            close_reason = self._close_reason(
                position=position,
                exit_order=exit_order,
            )
        else:
            recovered_exit = await self._recover_filled_stepped_stop_from_history(
                position=position,
                threshold_time=threshold_time,
            )
            if recovered_exit is None:
                (
                    exit_order,
                    is_liquidation,
                ) = await self._recover_filled_manual_close_from_history(
                    position=position,
                    threshold_time=threshold_time,
                )
                if is_liquidation:
                    close_reason = ClosedPositionReason.LIQUIDATION
                    provenance = ClosedPositionProvenance.LIQUIDATION_ORDER
                else:
                    close_reason = ClosedPositionReason.MANUAL_CLOSE
                    provenance = ClosedPositionProvenance.MANUAL_ORDER
            else:
                exit_order = recovered_exit
                close_reason = self._close_reason(
                    position=position,
                    exit_order=exit_order,
                )
        await service.stage(
            position=position,
            attempt=attempt,
            exit_order=exit_order,
            close_reason=close_reason,
            provenance=provenance,
        )
        return entry_identity

    async def _recover_filled_stepped_stop_from_history(
        self,
        *,
        position: Position,
        threshold_time: datetime | None = None,
    ) -> Order | None:
        """Recover one lost durable stepped-STOP identity through bounded GETs."""
        effective_threshold = (
            threshold_time if threshold_time is not None else position.opened_at
        )
        try:
            history = tuple(
                await self.exchange_client.get_protection_order_history(
                    symbol=position.symbol,
                    start_time=effective_threshold,
                )
            )
        except NotImplementedError:
            return None
        persisted_ids = {
            position.stop_loss_client_algo_id,
            position.take_profit_client_algo_id,
            position.pending_stop_loss_client_algo_id,
        }
        closing_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        candidates = tuple(
            order
            for order in history
            if order.client_order_id not in persisted_ids
            and Position.is_generated_stop_loss_client_algo_id(order.client_order_id)
            and order.symbol.upper() == position.symbol.upper()
            and order.created_at >= effective_threshold
            and order.side is closing_side
            and order.order_type in {OrderType.STOP_MARKET, OrderType.STOP}
            and order.status is OrderStatus.FILLED
            and order.quantity == position.quantity
            and order.executed_quantity == position.quantity
            and (order.execution_order_id is not None or bool(order.order_id))
            and self._is_tighter_stepped_stop(
                position=position,
                stop_price=order.stop_price,
            )
        )
        if len(candidates) > 1:
            raise RuntimeError(
                "Natural exit requires exactly one authoritative FILLED exit"
            )
        if not candidates:
            return None
        recovered = candidates[0]
        _LOGGER.warning(
            "Natural LIVE exit recovered a lost stepped STOP identity from "
            "authoritative history: symbol=%s old_client_id=%s "
            "exit_client_id=%s execution_order_id=%s",
            position.symbol,
            position.stop_loss_client_algo_id,
            recovered.client_order_id,
            recovered.execution_order_id,
        )
        return recovered

    async def _recover_filled_manual_close_from_history(
        self,
        *,
        position: Position,
        threshold_time: datetime | None = None,
    ) -> tuple[Order, bool]:
        """Recover one full manual close or liquidation from account fills."""
        closing_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        trades = tuple(
            await self.exchange_client.get_trades(
                symbol=position.symbol,
                limit=_MANUAL_CLOSE_TRADE_LIMIT,
            )
        )
        effective_threshold = (
            threshold_time if threshold_time is not None else position.opened_at
        )
        quantities_by_order: dict[str, Decimal] = {}
        for trade in trades:
            if (
                trade.symbol.upper() != position.symbol.upper()
                or trade.side is not closing_side
                or trade.executed_at < effective_threshold
            ):
                continue
            quantities_by_order[trade.order_id] = (
                quantities_by_order.get(trade.order_id, Decimal("0")) + trade.quantity
            )
        candidate_ids = tuple(
            sorted(
                order_id
                for order_id, quantity in quantities_by_order.items()
                if quantity == position.quantity
            )
        )
        if len(candidate_ids) > 1:
            raise RuntimeError(
                "Natural exit requires exactly one authoritative full manual-close "
                "order"
            )
        if len(candidate_ids) == 1:
            order_id = candidate_ids[0]
            recovered = await self.exchange_client.get_order(
                symbol=position.symbol,
                order_id=order_id,
            )
            if (
                recovered.client_order_id is None
                or not recovered.client_order_id.strip()
            ):
                recovered = replace(
                    recovered,
                    client_order_id=f"manual-{recovered.order_id}",
                )
            self._validate_manual_close_order(
                order=recovered,
                order_id=order_id,
                position=position,
                threshold_time=effective_threshold,
            )
            is_liquidation = any(
                trade.is_liquidation for trade in trades if trade.order_id == order_id
            )
            if is_liquidation:
                _LOGGER.error(
                    "Natural LIVE exit detected a LIQUIDATION execution from exchange "
                    "account history: symbol=%s exit_client_id=%s order_id=%s",
                    position.symbol,
                    recovered.client_order_id,
                    recovered.order_id,
                )
            else:
                _LOGGER.warning(
                    "Natural LIVE exit recovered a manual close from authoritative "
                    "account history: symbol=%s exit_client_id=%s order_id=%s",
                    position.symbol,
                    recovered.client_order_id,
                    recovered.order_id,
                )
            return recovered, is_liquidation

        # Candidate IDs is empty: ordinary exact manual-close matching did not
        # find an order matching stored_position.quantity.
        # In one-way position mode, an operator manual reversal executes an
        # opposite-side order strictly larger than the stored position (e.g.,
        # SELL 2Q to close LONG Q and open SHORT Q). Fall back to proving
        # the complete reversal sequence (Order A + subsequent Order B).
        return await self._recover_filled_manual_reversal_from_history(
            position=position,
            trades=trades,
            effective_threshold=effective_threshold,
        )

    async def _recover_filled_manual_reversal_from_history(
        self,
        *,
        position: Position,
        trades: Sequence[Trade],
        effective_threshold: datetime,
    ) -> tuple[Order, bool]:
        """Recover exit from a manual reversal and subsequent manual close sequence.

        In one-way position mode on derivatives/CFD exchanges, an operator
        reversing exposure (e.g. LONG -> SHORT) submits an opposite-side order
        with quantity strictly greater than the stored position quantity (e.g.
        SELL 2Q to close LONG Q and open SHORT Q).

        Ordinary exact manual-close matching fails in this scenario because
        the executed quantity of the reversal order exceeds
        stored_position.quantity. This fallback verifies the complete lifecycle:
        1. Order A on closing side with executed_quantity > position.quantity
           (excess quantity represents the new opposite exposure).
        2. Subsequent Order B on opposite side with executed_quantity == excess
           (closing the opposite exposure and returning the exchange to FLAT).
        3. Valid chronological ordering.
        4. Strict uniqueness (fail-closed if zero or multiple candidate
           sequences exist).
        """
        closing_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        opposite_side = (
            OrderSide.BUY if closing_side is OrderSide.SELL else OrderSide.SELL
        )
        old_quantity = position.quantity

        trades_by_order: dict[str, list[Trade]] = {}
        for trade in trades:
            if (
                trade.symbol.upper() != position.symbol.upper()
                or trade.executed_at < effective_threshold
            ):
                continue
            trades_by_order.setdefault(trade.order_id, []).append(trade)

        reversal_candidates: list[tuple[Order, Decimal, datetime, datetime]] = []
        for order_id, order_trades in trades_by_order.items():
            if not order_trades:
                continue
            if any(t.side is not closing_side for t in order_trades):
                continue
            trade_qty = sum((t.quantity for t in order_trades), start=Decimal("0"))
            if trade_qty <= old_quantity:
                continue

            try:
                order = await self.exchange_client.get_order(
                    symbol=position.symbol,
                    order_id=order_id,
                )
            except ExchangeOrderNotFoundError:
                continue

            if (
                order.order_id != order_id
                or order.symbol.upper() != position.symbol.upper()
                or order.side is not closing_side
                or order.status is not OrderStatus.FILLED
                or order.order_type not in {OrderType.MARKET, OrderType.LIMIT}
                or order.created_at < effective_threshold
                or order.quantity != order.executed_quantity
                or order.executed_quantity != trade_qty
                or order.executed_quantity <= old_quantity
            ):
                continue

            excess_qty = order.executed_quantity - old_quantity
            earliest_trade = min(t.executed_at for t in order_trades)
            latest_trade = max(t.executed_at for t in order_trades)
            reversal_candidates.append(
                (order, excess_qty, earliest_trade, latest_trade)
            )

        entry_order_id: str | None = None
        if position.entry_client_order_id is not None:
            attempt = await self.submission_attempt_repository.get_by_client_order_id(
                client_order_id=position.entry_client_order_id,
            )
            if attempt is not None:
                entry_order_id = attempt.exchange_order_id

        valid_sequences: list[tuple[Order, Order, Decimal]] = []
        for order_a, excess_qty, a_earliest, _a_latest in reversal_candidates:
            for order_b_id, b_trades in trades_by_order.items():
                if order_b_id == order_a.order_id:
                    continue
                if entry_order_id is not None and order_b_id == entry_order_id:
                    continue
                if any(t.side is not opposite_side for t in b_trades):
                    continue
                b_trade_qty = sum((t.quantity for t in b_trades), start=Decimal("0"))
                if b_trade_qty != excess_qty:
                    continue

                try:
                    order_b = await self.exchange_client.get_order(
                        symbol=position.symbol,
                        order_id=order_b_id,
                    )
                except ExchangeOrderNotFoundError:
                    continue

                if (
                    order_b.order_id != order_b_id
                    or order_b.symbol.upper() != position.symbol.upper()
                    or order_b.side is not opposite_side
                    or order_b.status is not OrderStatus.FILLED
                    or order_b.order_type not in {OrderType.MARKET, OrderType.LIMIT}
                    or order_b.quantity != order_b.executed_quantity
                    or order_b.executed_quantity != excess_qty
                ):
                    continue

                b_earliest = min(t.executed_at for t in b_trades)
                if order_b.created_at < order_a.created_at or b_earliest < a_earliest:
                    continue

                valid_sequences.append((order_a, order_b, excess_qty))

        if len(valid_sequences) > 1:
            _LOGGER.error(
                "Ambiguous manual reversal sequence: symbol=%s candidate_count=%d",
                position.symbol,
                len(valid_sequences),
            )
            raise RuntimeError(
                "Ambiguous manual reversal sequence detected during natural "
                "exit recovery"
            )

        if len(valid_sequences) == 0:
            raise RuntimeError(
                "Natural exit requires exactly one authoritative full manual-close "
                "order or proven reversal sequence"
            )

        order_a, order_b, excess_quantity = valid_sequences[0]
        _LOGGER.warning(
            "Natural LIVE exit recovered manual reversal sequence: symbol=%s "
            "stored_side=%s stored_qty=%s reverse_order_id=%s "
            "reverse_executed_qty=%s inferred_opposite_qty=%s "
            "subsequent_close_order_id=%s result=RECOVERED",
            position.symbol,
            position.side.value,
            position.quantity,
            order_a.order_id,
            order_a.executed_quantity,
            excess_quantity,
            order_b.order_id,
        )

        if order_a.client_order_id is None or not order_a.client_order_id.strip():
            order_a = replace(
                order_a,
                client_order_id=f"manual-{order_a.order_id}",
            )

        is_liquidation = any(
            t.is_liquidation for t in trades if t.order_id == order_a.order_id
        )
        return order_a, is_liquidation

    @staticmethod
    def _validate_manual_close_order(
        *,
        order: Order,
        order_id: str,
        position: Position,
        threshold_time: datetime | None = None,
    ) -> None:
        """Require one exact filled standard order for the full stored exposure."""
        closing_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        effective_threshold = (
            threshold_time if threshold_time is not None else position.opened_at
        )
        if (
            order.order_id != order_id
            or order.symbol.upper() != position.symbol.upper()
            or order.created_at < effective_threshold
            or order.side is not closing_side
            or order.order_type not in {OrderType.MARKET, OrderType.LIMIT}
            or order.status is not OrderStatus.FILLED
            or order.quantity != position.quantity
            or order.executed_quantity != position.quantity
            or order.client_order_id is None
            or not order.client_order_id.strip()
        ):
            raise RuntimeError(
                "Manual LIVE close order does not match the durable position"
            )

    async def _complete_closed_lifecycle_best_effort(
        self,
        *,
        entry_client_order_id: str,
    ) -> None:
        """Complete staged financial evidence after safety-critical cleanup."""
        service = self.closed_lifecycle_service
        if service is not None:
            await service.complete_best_effort(
                entry_client_order_id=entry_client_order_id,
            )

    @staticmethod
    def _close_reason(
        *,
        position: Position,
        exit_order: Order,
    ) -> ClosedPositionReason:
        """Classify one exact filled protection identity."""
        if exit_order.client_order_id == position.take_profit_client_algo_id:
            return ClosedPositionReason.TAKE_PROFIT
        if (
            exit_order.client_order_id == position.pending_stop_loss_client_algo_id
            or exit_order.client_order_id != position.stop_loss_client_algo_id
            or position.protection_step > 0
        ):
            return ClosedPositionReason.STEPPED_STOP
        return ClosedPositionReason.STOP_LOSS

    @staticmethod
    def _is_tighter_stepped_stop(
        *,
        position: Position,
        stop_price: Decimal | None,
    ) -> bool:
        """Require a replacement trigger strictly inside Entry-to-TP."""
        current_stop = position.stop_loss
        take_profit = position.take_profit
        if stop_price is None or current_stop is None or take_profit is None:
            return False
        if position.side is PositionSide.LONG:
            return (
                current_stop < stop_price or position.entry_price < stop_price
            ) and stop_price < take_profit
        return (
            stop_price < current_stop or stop_price < position.entry_price
        ) and take_profit < stop_price

    @staticmethod
    def _portfolio_snapshots_match(
        *,
        initial_positions: tuple[Position, ...],
        observed_positions: tuple[Position, ...],
    ) -> bool:
        """Require stable symbol, side, quantity, and entry-price exposure."""
        return LiveNaturalExitRecoveryService._to_exposure_by_symbol(
            positions=initial_positions
        ) == LiveNaturalExitRecoveryService._to_exposure_by_symbol(
            positions=observed_positions
        )

    @staticmethod
    def _to_exposure_by_symbol(
        *,
        positions: tuple[Position, ...],
    ) -> dict[str, tuple[PositionSide, Decimal, Decimal]]:
        """Return one exact non-price-sensitive exposure identity per symbol."""
        exposures: dict[str, tuple[PositionSide, Decimal, Decimal]] = {}
        for position in positions:
            symbol = position.symbol.upper()
            if symbol in exposures:
                raise RuntimeError(
                    "Exchange returned duplicate LIVE positions during "
                    f"natural-exit reconciliation: symbol={symbol}"
                )
            exposures[symbol] = (
                position.side,
                position.quantity,
                position.entry_price,
            )
        return exposures

    async def _validate_known_portfolio_transition(
        self,
        *,
        initial_positions: tuple[Position, ...],
        observed_positions: tuple[Position, ...],
        stored_by_symbol: dict[str, Position],
    ) -> None:
        """Accept only a durable protected entry or known natural-exit transition."""
        initial = self._to_exposure_by_symbol(positions=initial_positions)
        observed = self._to_exposure_by_symbol(positions=observed_positions)
        for symbol in sorted(observed.keys() - initial.keys()):
            exchange_position = next(
                position
                for position in observed_positions
                if position.symbol.upper() == symbol
            )
            await self._require_durable_protected_entry(
                exchange_position=exchange_position,
                stored_position=stored_by_symbol.get(symbol),
            )
        for symbol in sorted(initial.keys() - observed.keys()):
            if symbol not in stored_by_symbol:
                raise RuntimeError(
                    "LIVE portfolio lost an unmanaged exposure during "
                    f"natural-exit reconciliation: symbol={symbol}"
                )
        for symbol in sorted(initial.keys() & observed.keys()):
            if initial[symbol] != observed[symbol]:
                raise RuntimeError(
                    "LIVE exposure changed during natural-exit reconciliation: "
                    f"symbol={symbol}"
                )

    async def _require_durable_protected_entry(
        self,
        *,
        exchange_position: Position,
        stored_position: Position | None,
    ) -> None:
        """Prove a newly visible exposure belongs to one completed protected entry."""
        if stored_position is None:
            raise RuntimeError(
                "LIVE portfolio gained an unmanaged exposure during natural-exit "
                f"reconciliation: symbol={exchange_position.symbol}"
            )
        if (
            exchange_position.symbol.upper() != stored_position.symbol.upper()
            or exchange_position.side is not stored_position.side
            or exchange_position.quantity != stored_position.quantity
            or exchange_position.entry_price != stored_position.entry_price
            or stored_position.interval is None
            or stored_position.strategy_type is None
        ):
            raise RuntimeError(
                "LIVE portfolio gained exposure that does not match its durable "
                f"position: symbol={exchange_position.symbol}"
            )
        entry_client_order_id = stored_position.entry_client_order_id
        if entry_client_order_id is None:
            raise RuntimeError(
                "LIVE portfolio gained exposure without a durable entry identity: "
                f"symbol={exchange_position.symbol}"
            )
        attempt = await self.submission_attempt_repository.get_by_client_order_id(
            client_order_id=entry_client_order_id,
        )
        expected_side = (
            OrderSide.BUY
            if stored_position.side is PositionSide.LONG
            else OrderSide.SELL
        )
        if (
            attempt is None
            or attempt.status is not SubmissionAttemptStatus.COMPLETED
            or attempt.symbol.upper() != stored_position.symbol.upper()
            or attempt.side is not expected_side
            or attempt.quantity != stored_position.quantity
        ):
            raise RuntimeError(
                "LIVE portfolio gained exposure without a completed durable entry: "
                f"symbol={exchange_position.symbol}"
            )
        await self._require_active_persisted_leg(
            position=stored_position,
            order_type=OrderType.STOP_MARKET,
            client_id=stored_position.stop_loss_client_algo_id,
            trigger=stored_position.stop_loss,
        )
        await self._require_active_persisted_leg(
            position=stored_position,
            order_type=OrderType.TAKE_PROFIT_MARKET,
            client_id=stored_position.take_profit_client_algo_id,
            trigger=stored_position.take_profit,
        )

    async def _require_active_persisted_leg(
        self,
        *,
        position: Position,
        order_type: OrderType,
        client_id: str | None,
        trigger: Decimal | None,
    ) -> None:
        """Require one exact durable protection identity to be currently active."""
        if client_id is None or trigger is None:
            raise RuntimeError(
                "Newly visible LIVE exposure is missing durable protection: "
                f"symbol={position.symbol}"
            )
        order = await self.exchange_client.get_protection_order_by_client_id(
            symbol=position.symbol,
            client_id=client_id,
        )
        self._validate_persisted_leg_identity(
            order=order,
            position=position,
            order_type=order_type,
            client_id=client_id,
            trigger=trigger,
        )
        if order.status is not OrderStatus.NEW:
            raise RuntimeError(
                "Newly visible LIVE exposure has inactive protection: "
                f"symbol={position.symbol}"
            )

    async def _reconcile_persisted_protection_before_delete(
        self,
        *,
        position: Position,
    ) -> tuple[Order, ...]:
        """Resolve every durable protection identity before deleting local state."""
        legs = (
            (
                OrderType.STOP_MARKET,
                position.stop_loss_client_algo_id,
                position.stop_loss,
            ),
            (
                OrderType.TAKE_PROFIT_MARKET,
                position.take_profit_client_algo_id,
                position.take_profit,
            ),
            (
                OrderType.STOP_MARKET,
                position.pending_stop_loss_client_algo_id,
                position.pending_stop_loss,
            ),
        )
        filled_orders: list[Order] = []
        for order_type, client_id, trigger in legs:
            if client_id is None:
                continue
            filled_order = await self._reconcile_persisted_leg_before_delete(
                position=position,
                order_type=order_type,
                client_id=client_id,
                trigger=trigger,
            )
            if filled_order is not None:
                filled_orders.append(filled_order)
        return tuple(filled_orders)

    async def _reconcile_persisted_leg_before_delete(
        self,
        *,
        position: Position,
        order_type: OrderType,
        client_id: str,
        trigger: Decimal | None,
    ) -> Order | None:
        """Make one durable protection leg provably inactive before deletion."""
        try:
            order = await self.exchange_client.get_protection_order_by_client_id(
                symbol=position.symbol,
                client_id=client_id,
            )
        except ExchangeOrderNotFoundError:
            return None
        except ExchangeOrderOutcomeUnknownError as error:
            raise RuntimeError(
                "Persisted LIVE protection identity could not be verified "
                "before natural-exit deletion"
            ) from error

        self._validate_persisted_leg_identity(
            order=order,
            position=position,
            order_type=order_type,
            client_id=client_id,
            trigger=trigger,
        )
        if order.status in _TERMINAL_PROTECTION_STATUSES:
            return order if order.status is OrderStatus.FILLED else None
        if order.status is not OrderStatus.NEW:
            raise RuntimeError(
                "Persisted LIVE protection is neither active nor terminal "
                "before natural-exit deletion"
            )

        await self._cancel_and_reconcile(order=order)
        await self._prove_persisted_leg_inactive(
            position=position,
            order_type=order_type,
            client_id=client_id,
            trigger=trigger,
        )
        return None

    async def _prove_persisted_leg_inactive(
        self,
        *,
        position: Position,
        order_type: OrderType,
        client_id: str,
        trigger: Decimal | None,
    ) -> None:
        """Prove an exact durable leg is terminal or absent after one DELETE."""
        last_unknown: ExchangeOrderOutcomeUnknownError | None = None
        for attempt in range(_RECONCILIATION_ATTEMPTS):
            try:
                order = await self.exchange_client.get_protection_order_by_client_id(
                    symbol=position.symbol,
                    client_id=client_id,
                )
            except ExchangeOrderNotFoundError:
                return
            except ExchangeOrderOutcomeUnknownError as error:
                last_unknown = error
            else:
                last_unknown = None
                self._validate_persisted_leg_identity(
                    order=order,
                    position=position,
                    order_type=order_type,
                    client_id=client_id,
                    trigger=trigger,
                )
                if order.status in _TERMINAL_PROTECTION_STATUSES:
                    return
                if order.status is not OrderStatus.NEW:
                    raise RuntimeError(
                        "Persisted LIVE protection entered an unexpected state "
                        "during natural-exit cleanup"
                    )

            if attempt + 1 < _RECONCILIATION_ATTEMPTS:
                await asyncio.sleep(_RECONCILIATION_DELAY_SECONDS)

        if last_unknown is not None:
            raise RuntimeError(
                "Persisted LIVE protection identity remains unverifiable "
                "after natural-exit cleanup"
            ) from last_unknown

        raise RuntimeError(
            "Persisted LIVE protection remains active after natural-exit cleanup"
        )

    @staticmethod
    def _validate_persisted_leg_identity(
        *,
        order: Order,
        position: Position,
        order_type: OrderType,
        client_id: str,
        trigger: Decimal | None,
    ) -> None:
        """Require exact durable identity and shape without assuming active state."""
        expected_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        expected_types = (
            {OrderType.STOP_MARKET, OrderType.STOP}
            if order_type in (OrderType.STOP_MARKET, OrderType.STOP)
            else {OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT}
        )
        valid_quantity = (
            order.quantity == position.quantity
            or (position.partial_tp_executed and order.quantity >= position.quantity)
            or order.quantity > Decimal("0")
        )
        if (
            trigger is None
            or order.client_order_id != client_id
            or order.symbol.upper() != position.symbol.upper()
            or order.side is not expected_side
            or order.order_type not in expected_types
            or not valid_quantity
            or order.stop_price is None
        ):
            raise RuntimeError(
                "Persisted LIVE protection does not match its durable position leg"
            )
        if order.stop_price != trigger:
            _LOGGER.warning(
                "Persisted LIVE protection trigger differs from stored trigger "
                "(order=%s stored=%s) for symbol=%s; reconciling deletion",
                order.stop_price,
                trigger,
                position.symbol,
            )

    async def _cancel_and_reconcile(self, *, order: Order) -> None:
        """Attempt one DELETE and prove its exact identity is inactive."""
        client_id = order.client_order_id
        order_id = order.order_id
        if client_id is None and not order_id:
            raise RuntimeError("Orphan protection is missing its client identity")

        ambiguous_error: ExchangeOrderOutcomeUnknownError | None = None
        try:
            await self.exchange_client.cancel_protection_order(
                symbol=order.symbol,
                client_id=client_id,
                order_id=order_id,
            )
        except asyncio.CancelledError:
            raise
        except ExchangeOrderOutcomeUnknownError as error:
            ambiguous_error = error

        last_unknown: ExchangeOrderOutcomeUnknownError | None = None
        for attempt in range(_RECONCILIATION_ATTEMPTS):
            try:
                if client_id is not None:
                    remaining = (
                        await self.exchange_client.get_protection_order_by_client_id(
                            symbol=order.symbol,
                            client_id=client_id,
                        )
                    )
                else:
                    open_orders = await self.exchange_client.get_open_protection_orders(
                        symbol=order.symbol
                    )
                    clean_target_id = (
                        order_id[:-3] if order_id.endswith(("-tp", "-sl")) else order_id
                    )
                    matching = [
                        o
                        for o in open_orders
                        if o.order_id == order_id
                        or (
                            clean_target_id
                            and (
                                o.order_id[:-3]
                                if o.order_id.endswith(("-tp", "-sl"))
                                else o.order_id
                            )
                            == clean_target_id
                        )
                    ]
                    if not matching:
                        return
                    remaining = matching[0]
            except ExchangeOrderNotFoundError:
                return
            except ExchangeOrderOutcomeUnknownError as error:
                last_unknown = error
            else:
                last_unknown = None
                if remaining.status in _TERMINAL_PROTECTION_STATUSES:
                    return
                if remaining.status is not OrderStatus.NEW:
                    raise RuntimeError(
                        "LIVE orphan protection entered an unexpected state "
                        "during cancellation"
                    )

            if attempt + 1 < _RECONCILIATION_ATTEMPTS:
                await asyncio.sleep(_RECONCILIATION_DELAY_SECONDS)

        if ambiguous_error is not None:
            raise RuntimeError(
                "Ambiguous LIVE orphan-protection cancellation remains unresolved"
            ) from ambiguous_error
        if last_unknown is not None:
            raise RuntimeError(
                "LIVE orphan-protection identity remains unverifiable after "
                "cancellation"
            ) from last_unknown

        raise RuntimeError("LIVE orphan protection remains active after cancellation")

    @staticmethod
    def _validate_owned_orphan(*, order: Order, position: Position) -> None:
        """Require an exact persisted protection identity before cancellation."""
        client_id = order.client_order_id
        expected_types: set[OrderType] | None = None
        expected_trigger = None

        if client_id is not None and client_id == position.stop_loss_client_algo_id:
            expected_types = {OrderType.STOP_MARKET, OrderType.STOP}
            expected_trigger = position.stop_loss
        elif client_id is not None and client_id == position.take_profit_client_algo_id:
            expected_types = {OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT}
            expected_trigger = position.take_profit
        elif (
            client_id is not None
            and client_id == position.pending_stop_loss_client_algo_id
        ):
            expected_types = {OrderType.STOP_MARKET, OrderType.STOP}
            expected_trigger = position.pending_stop_loss
        elif Position.is_generated_stop_loss_client_algo_id(client_id):
            expected_types = {OrderType.STOP_MARKET, OrderType.STOP}
            expected_trigger = order.stop_price
        elif Position.is_generated_take_profit_client_algo_id(client_id):
            expected_types = {OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT}
            expected_trigger = order.stop_price
        elif client_id is None and order.order_id:
            if order.order_type in (
                OrderType.TAKE_PROFIT_MARKET,
                OrderType.TAKE_PROFIT,
            ):
                expected_types = {OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT}
                expected_trigger = position.take_profit or order.stop_price
            elif order.order_type in (OrderType.STOP_MARKET, OrderType.STOP):
                expected_types = {OrderType.STOP_MARKET, OrderType.STOP}
                expected_trigger = position.stop_loss or order.stop_price

        if expected_types is None:
            raise RuntimeError(
                "LIVE orphan protection does not match a durable client identity"
            )

        expected_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        valid_quantity = (
            order.quantity == position.quantity
            or (position.partial_tp_executed and order.quantity >= position.quantity)
            or order.quantity > Decimal("0")
        )

        if (
            order.symbol.upper() != position.symbol.upper()
            or order.side is not expected_side
            or order.order_type not in expected_types
            or order.status is not OrderStatus.NEW
            or not valid_quantity
            or order.stop_price is None
            or expected_trigger is None
        ):
            raise RuntimeError(
                "LIVE orphan protection does not match its durable position leg"
            )

        if order.stop_price != expected_trigger:
            _LOGGER.warning(
                "LIVE orphan protection trigger differs from stored trigger "
                "(order=%s stored=%s) for symbol=%s; canceling to prevent "
                "naked exposure",
                order.stop_price,
                expected_trigger,
                position.symbol,
            )
