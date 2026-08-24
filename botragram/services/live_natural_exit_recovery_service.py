"""Recover natural LIVE exits and remove proven orphan protection."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from botragram.enums import (
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
from botragram.models import Order, Position
from botragram.repositories import PositionRepository, SubmissionAttemptRepository

__all__ = [
    "LiveNaturalExitRecoveryService",
]


_RECONCILIATION_ATTEMPTS: Final[int] = 3
_RECONCILIATION_DELAY_SECONDS: Final[float] = 0.5
_PORTFOLIO_STABILITY_ATTEMPTS: Final[int] = 3
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

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        """Return one conditional protection order by durable identity."""
        ...

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> None:
        """Attempt one exact conditional protection cancellation."""
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

    async def reconcile(self) -> None:
        """Remove proven orphan protection and stale local positions."""
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
            if stored_position is None:
                raise RuntimeError(
                    "LIVE orphan protection has no durable position identity: "
                    f"symbol={symbol}"
                )
            orders = tuple(orphan_groups[symbol])
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
            await self._reconcile_persisted_protection_before_delete(position=position)
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
            await self.position_repository.delete(symbol=position.symbol)
            _LOGGER.info(
                "Natural LIVE exit reconciled: symbol=%s entry_client_order_id=%s",
                position.symbol,
                position.entry_client_order_id,
            )

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
    ) -> None:
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
        for order_type, client_id, trigger in legs:
            if client_id is None:
                continue
            await self._reconcile_persisted_leg_before_delete(
                position=position,
                order_type=order_type,
                client_id=client_id,
                trigger=trigger,
            )

    async def _reconcile_persisted_leg_before_delete(
        self,
        *,
        position: Position,
        order_type: OrderType,
        client_id: str,
        trigger: Decimal | None,
    ) -> None:
        """Make one durable protection leg provably inactive before deletion."""
        try:
            order = await self.exchange_client.get_protection_order_by_client_id(
                symbol=position.symbol,
                client_id=client_id,
            )
        except ExchangeOrderNotFoundError:
            return
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
            return
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
        if (
            trigger is None
            or order.client_order_id != client_id
            or order.symbol.upper() != position.symbol.upper()
            or order.side is not expected_side
            or order.order_type is not order_type
            or order.quantity != position.quantity
            or order.stop_price is None
            or order.stop_price != trigger
        ):
            raise RuntimeError(
                "Persisted LIVE protection does not match its durable position leg"
            )

    async def _cancel_and_reconcile(self, *, order: Order) -> None:
        """Attempt one DELETE and prove its exact identity is inactive."""
        client_id = order.client_order_id
        if client_id is None:
            raise RuntimeError("Orphan protection is missing its client identity")

        ambiguous_error: ExchangeOrderOutcomeUnknownError | None = None
        try:
            await self.exchange_client.cancel_protection_order(
                symbol=order.symbol,
                client_id=client_id,
            )
        except asyncio.CancelledError:
            raise
        except ExchangeOrderOutcomeUnknownError as error:
            ambiguous_error = error

        last_unknown: ExchangeOrderOutcomeUnknownError | None = None
        for attempt in range(_RECONCILIATION_ATTEMPTS):
            try:
                remaining = (
                    await self.exchange_client.get_protection_order_by_client_id(
                        symbol=order.symbol,
                        client_id=client_id,
                    )
                )
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
        expected_type: OrderType | None = None
        expected_trigger = None

        if client_id == position.stop_loss_client_algo_id:
            expected_type = OrderType.STOP_MARKET
            expected_trigger = position.stop_loss
        elif client_id == position.take_profit_client_algo_id:
            expected_type = OrderType.TAKE_PROFIT_MARKET
            expected_trigger = position.take_profit
        elif client_id == position.pending_stop_loss_client_algo_id:
            expected_type = OrderType.STOP_MARKET
            expected_trigger = position.pending_stop_loss

        if expected_type is None:
            raise RuntimeError(
                "LIVE orphan protection does not match a durable client identity"
            )

        expected_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )

        if (
            order.symbol.upper() != position.symbol.upper()
            or order.side is not expected_side
            or order.order_type is not expected_type
            or order.status is not OrderStatus.NEW
            or order.quantity != position.quantity
            or order.stop_price is None
            or expected_trigger is None
            or order.stop_price != expected_trigger
        ):
            raise RuntimeError(
                "LIVE orphan protection does not match its durable position leg"
            )
