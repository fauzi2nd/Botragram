"""Recover natural LIVE exits and remove proven orphan protection."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from botragram.enums import OrderSide, OrderStatus, OrderType, PositionSide
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
)
from botragram.models import Order, Position
from botragram.repositories import PositionRepository, SubmissionAttemptRepository

__all__ = [
    "LiveNaturalExitRecoveryService",
]


_RECONCILIATION_ATTEMPTS: Final[int] = 2
_RECONCILIATION_DELAY_SECONDS: Final[float] = 0.05
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

        stored_positions = tuple(await self.position_repository.get_all())
        stored_by_symbol = {
            position.symbol.upper(): position for position in stored_positions
        }

        initial_positions = tuple(await self.exchange_client.get_positions())
        initial_active_symbols = {
            position.symbol.upper() for position in initial_positions
        }
        open_protections = tuple(
            await self.exchange_client.get_open_protection_orders()
        )

        orphan_groups: dict[str, list[Order]] = {}
        for order in open_protections:
            symbol = order.symbol.upper()
            if symbol in initial_active_symbols:
                continue
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
                self._validate_owned_orphan(
                    order=order,
                    position=stored_position,
                )

            for order in sorted(
                orders,
                key=lambda candidate: (
                    candidate.order_type.value,
                    candidate.client_order_id or "",
                ),
            ):
                await self._cancel_and_reconcile(order=order)

        final_positions = tuple(await self.exchange_client.get_positions())
        final_active_symbols = {position.symbol.upper() for position in final_positions}
        final_protections = tuple(
            await self.exchange_client.get_open_protection_orders()
        )

        if final_active_symbols != initial_active_symbols:
            raise RuntimeError(
                "LIVE portfolio changed during natural-exit reconciliation"
            )

        remaining_orphans = tuple(
            order
            for order in final_protections
            if order.symbol.upper() not in final_active_symbols
        )
        if remaining_orphans:
            raise RuntimeError(
                "LIVE orphan protection remains after reconciliation: "
                f"count={len(remaining_orphans)}"
            )

        for position in stored_positions:
            if position.symbol.upper() in final_active_symbols:
                continue
            await self._reconcile_persisted_protection_before_delete(
                position=position,
            )
            if await self.exchange_client.get_positions(symbol=position.symbol):
                raise RuntimeError(
                    "LIVE exposure reappeared before durable position deletion: "
                    f"symbol={position.symbol}"
                )
            remaining_symbol_protections = tuple(
                await self.exchange_client.get_open_protection_orders(
                    symbol=position.symbol,
                )
            )
            if remaining_symbol_protections:
                raise RuntimeError(
                    "LIVE protection remains before durable position deletion: "
                    f"symbol={position.symbol} "
                    f"count={len(remaining_symbol_protections)}"
                )
            await self.position_repository.delete(symbol=position.symbol)
            _LOGGER.info(
                "Natural LIVE exit reconciled: symbol=%s entry_client_order_id=%s",
                position.symbol,
                position.entry_client_order_id,
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
