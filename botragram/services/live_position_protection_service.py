"""Reconcile and verify Futures protection for one live position."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from botragram.engine import RiskEngine
from botragram.enums import OrderSide, OrderStatus, OrderType, PositionSide
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
)
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Order, Position
from botragram.repositories import PositionRepository

__all__ = ["LivePositionProtectionService"]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_RECONCILIATION_MAX_ATTEMPTS: Final[int] = 2
_RECONCILIATION_DELAY_SECONDS: Final[float] = 0.05
_TERMINAL_PROTECTION_STATUSES: Final[frozenset[OrderStatus]] = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


@dataclass(slots=True, kw_only=True, frozen=True)
class LivePositionProtectionService:
    """Ensure one Futures position has exchange-verified SL and TP coverage."""

    exchange_client: BaseExchangeClient
    position_repository: PositionRepository
    risk_engine: RiskEngine

    async def validate_pre_entry_plan(
        self,
        *,
        symbol: str,
        position_side: PositionSide,
        stop_loss: Decimal,
        take_profit: Decimal,
    ) -> None:
        """Reject a protection plan that is already invalid before entry mutation."""
        rules = await self.exchange_client.get_market_entry_rules(symbol=symbol)
        mark_price = await self.exchange_client.get_mark_price(symbol=symbol)
        normalized_stop = rules.normalize_protection_trigger(
            raw_trigger_price=stop_loss,
            position_side=position_side,
            order_type=OrderType.STOP_MARKET,
            mark_price=mark_price,
        )
        normalized_take_profit = rules.normalize_protection_trigger(
            raw_trigger_price=take_profit,
            position_side=position_side,
            order_type=OrderType.TAKE_PROFIT_MARKET,
            mark_price=mark_price,
        )
        _LOGGER.info(
            "Pre-entry protection plan verified: symbol=%s mark_price=%s "
            "stop_loss=%s take_profit=%s",
            symbol,
            mark_price,
            normalized_stop,
            normalized_take_profit,
        )

    async def ensure(self, *, position: Position) -> Position:
        """Reconcile SL/TP orders and persist their verified trigger prices.

        Raises:
            RuntimeError: If the exchange cannot prove complete protection.
        """
        protection_orders = await self.exchange_client.get_open_protection_orders(
            symbol=position.symbol,
        )
        stop_order: Order | None = None
        take_profit_order: Order | None = None
        if position.stop_loss_client_algo_id is None:
            stop_order = self._find_protection_order(
                orders=protection_orders,
                position=position,
                order_type=OrderType.STOP_MARKET,
            )
        if position.take_profit_client_algo_id is None:
            take_profit_order = self._find_protection_order(
                orders=protection_orders,
                position=position,
                order_type=OrderType.TAKE_PROFIT_MARKET,
            )

        # A client identity retained from an earlier process cannot prove whether
        # its POST was never attempted or reached the exchange before a crash.
        # Resolve it first and fail closed on an unprovable outcome.  Only
        # identities created during this invocation may proceed directly to POST.
        if position.stop_loss_client_algo_id is not None:
            stop_order = await self._recover_persisted_leg(
                position=position,
                order_type=OrderType.STOP_MARKET,
                client_id=position.stop_loss_client_algo_id,
            )
        if position.take_profit_client_algo_id is not None:
            take_profit_order = await self._recover_persisted_leg(
                position=position,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=position.take_profit_client_algo_id,
            )

        if stop_order is None or take_profit_order is None:
            (
                normalized_stop,
                normalized_take_profit,
            ) = await self._normalize_missing_protection_plan(
                position=position,
                needs_stop_loss=stop_order is None,
                needs_take_profit=take_profit_order is None,
            )
            _LOGGER.info(
                "Live protection reconciliation started: symbol=%s missing_stop=%s "
                "missing_take_profit=%s",
                position.symbol,
                stop_order is None,
                take_profit_order is None,
            )
            if stop_order is None:
                if normalized_stop is None:
                    raise RuntimeError("Missing STOP plan was not normalized")
                position = self._with_missing_client_algo_ids(
                    position=replace(position, stop_loss=normalized_stop),
                    needs_stop_loss=True,
                    needs_take_profit=False,
                )
                await self.position_repository.save(position=position)
                await self._submit_missing_leg(
                    position=position,
                    order_type=OrderType.STOP_MARKET,
                    trigger_price=normalized_stop,
                    client_id=self._require_client_id(
                        position.stop_loss_client_algo_id
                    ),
                )
                stop_order = await self._get_verified_submitted_leg(
                    position=position,
                    order_type=OrderType.STOP_MARKET,
                )
            if take_profit_order is None:
                if normalized_take_profit is None:
                    raise RuntimeError("Missing TAKE_PROFIT plan was not normalized")
                position = self._with_missing_client_algo_ids(
                    position=replace(position, take_profit=normalized_take_profit),
                    needs_stop_loss=False,
                    needs_take_profit=True,
                )
                await self.position_repository.save(position=position)
                await self._submit_missing_leg(
                    position=position,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                    trigger_price=normalized_take_profit,
                    client_id=self._require_client_id(
                        position.take_profit_client_algo_id
                    ),
                )
                take_profit_order = await self._get_verified_submitted_leg(
                    position=position,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                )

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

    async def _normalize_missing_protection_plan(
        self,
        *,
        position: Position,
        needs_stop_loss: bool,
        needs_take_profit: bool,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Return fresh venue-valid triggers for only the missing protection legs.

        A persisted client identity means the corresponding trigger is already
        durable mutation intent. If that identity is authoritatively NOT_FOUND
        after restart, reuse and revalidate that exact durable trigger rather
        than silently recalculating it from possibly changed risk settings.
        """
        if not needs_stop_loss and not needs_take_profit:
            return None, None

        raw_stop: Decimal | None = None
        raw_take_profit: Decimal | None = None
        if (needs_stop_loss and position.stop_loss_client_algo_id is None) or (
            needs_take_profit and position.take_profit_client_algo_id is None
        ):
            raw_stop, raw_take_profit = self.risk_engine.calculate_protection_levels(
                side=position.side,
                entry_price=position.entry_price,
                strategy_type=position.strategy_type,
            )

        rules = await self.exchange_client.get_market_entry_rules(
            symbol=position.symbol,
        )
        mark_price = await self.exchange_client.get_mark_price(symbol=position.symbol)

        normalized_stop: Decimal | None = None
        if needs_stop_loss:
            stop_source = (
                position.stop_loss
                if position.stop_loss_client_algo_id is not None
                else raw_stop
            )
            if stop_source is None:
                raise RuntimeError(
                    "Persisted LIVE STOP identity is missing its durable trigger"
                )
            normalized_stop = rules.normalize_protection_trigger(
                raw_trigger_price=stop_source,
                position_side=position.side,
                order_type=OrderType.STOP_MARKET,
                mark_price=mark_price,
            )

        normalized_take_profit: Decimal | None = None
        if needs_take_profit:
            take_profit_source = (
                position.take_profit
                if position.take_profit_client_algo_id is not None
                else raw_take_profit
            )
            if take_profit_source is None:
                raise RuntimeError(
                    "Persisted LIVE TAKE_PROFIT identity is missing its durable trigger"
                )
            normalized_take_profit = rules.normalize_protection_trigger(
                raw_trigger_price=take_profit_source,
                position_side=position.side,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                mark_price=mark_price,
            )

        return normalized_stop, normalized_take_profit

    async def _get_verified_submitted_leg(
        self,
        *,
        position: Position,
        order_type: OrderType,
    ) -> Order:
        """Verify a newly submitted leg only through its exact durable identity."""
        client_id = (
            position.stop_loss_client_algo_id
            if order_type is OrderType.STOP_MARKET
            else position.take_profit_client_algo_id
        )
        if client_id is None:
            raise RuntimeError(
                "Submitted protection leg is missing its client identity"
            )

        try:
            order = await self.exchange_client.get_protection_order_by_client_id(
                symbol=position.symbol,
                client_id=client_id,
            )
        except ExchangeOrderNotFoundError as error:
            raise RuntimeError(
                "Exchange did not confirm submitted protection identity"
            ) from error
        except ExchangeOrderOutcomeUnknownError as error:
            raise RuntimeError(
                "Submitted protection identity could not be verified"
            ) from error

        self._validate_reconciled_leg(
            order=order,
            position=position,
            order_type=order_type,
            client_id=client_id,
        )
        return order

    async def _submit_missing_leg(
        self,
        *,
        position: Position,
        order_type: OrderType,
        trigger_price: Decimal,
        client_id: str,
    ) -> None:
        """POST one leg once, reconciling only an ambiguous outcome by GET."""
        try:
            await self.exchange_client.create_protection_orders(
                symbol=position.symbol,
                side=self._closing_side(position.side),
                quantity=position.quantity,
                stop_loss=(
                    trigger_price if order_type is OrderType.STOP_MARKET else None
                ),
                take_profit=(
                    trigger_price
                    if order_type is OrderType.TAKE_PROFIT_MARKET
                    else None
                ),
                stop_loss_client_algo_id=(
                    client_id if order_type is OrderType.STOP_MARKET else None
                ),
                take_profit_client_algo_id=(
                    client_id if order_type is OrderType.TAKE_PROFIT_MARKET else None
                ),
            )
        except ExchangeOrderOutcomeUnknownError:
            await self._reconcile_ambiguous_leg(
                position=position,
                order_type=order_type,
                client_id=client_id,
            )

    async def _reconcile_ambiguous_leg(
        self,
        *,
        position: Position,
        order_type: OrderType,
        client_id: str,
    ) -> None:
        """Prove an ambiguous protection POST through bounded GET-only reads."""
        for attempt in range(_RECONCILIATION_MAX_ATTEMPTS):
            try:
                order = await self.exchange_client.get_protection_order_by_client_id(
                    symbol=position.symbol,
                    client_id=client_id,
                )
            except ExchangeOrderNotFoundError, ExchangeOrderOutcomeUnknownError:
                if attempt + 1 < _RECONCILIATION_MAX_ATTEMPTS:
                    await asyncio.sleep(_RECONCILIATION_DELAY_SECONDS)
                    continue
                break

            self._validate_reconciled_leg(
                order=order,
                position=position,
                order_type=order_type,
                client_id=client_id,
            )
            return

        raise RuntimeError("Ambiguous LIVE protection mutation remains unresolved")

    async def _recover_persisted_leg(
        self,
        *,
        position: Position,
        order_type: OrderType,
        client_id: str,
    ) -> Order | None:
        """Prove a pre-restart protection mutation through one authoritative GET.

        A transport-uncertain result remains terminal for this recovery pass.
        An authoritative not-found result returns ``None`` so the caller may
        revalidate and recreate the same durable identity without inventing a
        second mutation identity.

        Args:
            position: The live position that requires protection.
            order_type: The logical protection leg to recover.
            client_id: The durable exchange client identity for that leg.

        Returns:
            The authoritative matching protection order, or ``None`` when the
            exact durable identity is authoritatively absent.

        Raises:
            RuntimeError: If the protection mutation cannot be proven.
        """
        try:
            order = await self.exchange_client.get_protection_order_by_client_id(
                symbol=position.symbol,
                client_id=client_id,
            )
        except ExchangeOrderNotFoundError:
            _LOGGER.warning(
                "Persisted LIVE protection identity is absent; the same durable "
                "identity may be recreated after fresh venue validation: "
                "symbol=%s type=%s client_id=%s",
                position.symbol,
                order_type.value,
                client_id,
            )
            return None
        except ExchangeOrderOutcomeUnknownError as error:
            raise RuntimeError(
                "Persisted LIVE protection identity could not be verified"
            ) from error

        self._validate_reconciled_leg(
            order=order,
            position=position,
            order_type=order_type,
            client_id=client_id,
        )
        return order

    async def cancel_persisted_legs(self, *, position: Position) -> None:
        """Cancel only exact durable protection identities and prove them absent."""
        for order_type, client_id in (
            (OrderType.STOP_MARKET, position.stop_loss_client_algo_id),
            (OrderType.TAKE_PROFIT_MARKET, position.take_profit_client_algo_id),
        ):
            if client_id is None:
                continue

            try:
                order = await self.exchange_client.get_protection_order_by_client_id(
                    symbol=position.symbol,
                    client_id=client_id,
                )
            except ExchangeOrderNotFoundError:
                continue
            except ExchangeOrderOutcomeUnknownError as error:
                raise RuntimeError(
                    "Persisted LIVE protection identity could not be verified "
                    "before cleanup"
                ) from error

            self._validate_reconciled_leg_identity(
                order=order,
                position=position,
                order_type=order_type,
                client_id=client_id,
            )
            if order.status in _TERMINAL_PROTECTION_STATUSES:
                continue
            if order.status is not OrderStatus.NEW:
                raise RuntimeError(
                    "Persisted LIVE protection is neither active nor terminal"
                )

            ambiguous_error: ExchangeOrderOutcomeUnknownError | None = None
            try:
                await self.exchange_client.cancel_protection_order(
                    symbol=position.symbol,
                    client_id=client_id,
                )
            except ExchangeOrderOutcomeUnknownError as error:
                ambiguous_error = error

            for attempt in range(_RECONCILIATION_MAX_ATTEMPTS):
                remaining = tuple(
                    await self.exchange_client.get_open_protection_orders(
                        symbol=position.symbol,
                    )
                )
                if not any(
                    candidate.client_order_id == client_id for candidate in remaining
                ):
                    break
                if attempt + 1 < _RECONCILIATION_MAX_ATTEMPTS:
                    await asyncio.sleep(_RECONCILIATION_DELAY_SECONDS)
            else:
                if ambiguous_error is not None:
                    raise RuntimeError(
                        "Ambiguous LIVE protection cleanup remains unresolved"
                    ) from ambiguous_error
                raise RuntimeError(
                    "Exchange still reports persisted LIVE protection after cleanup"
                )

    async def probe_persisted_leg(
        self,
        *,
        position: Position,
        order_type: OrderType,
        client_id: str,
    ) -> str:
        """GET-only probe of a persisted protection client identity.

        Returns one of: "not_found", "active", "terminal", "unexpected", "unknown".
        Does not perform any POST or mutation.
        """
        try:
            order = await self.exchange_client.get_protection_order_by_client_id(
                symbol=position.symbol,
                client_id=client_id,
            )
        except ExchangeOrderNotFoundError:
            return "not_found"
        except ExchangeOrderOutcomeUnknownError:
            return "unknown"

        try:
            self._validate_reconciled_leg_identity(
                order=order,
                position=position,
                order_type=order_type,
                client_id=client_id,
            )
        except RuntimeError:
            return "unexpected"

        if order.status is OrderStatus.NEW:
            return "active"
        if order.status in _TERMINAL_PROTECTION_STATUSES:
            return "terminal"
        return "unexpected"

    @staticmethod
    def _validate_reconciled_leg_identity(
        *,
        order: Order,
        position: Position,
        order_type: OrderType,
        client_id: str,
    ) -> None:
        """Reject a queried algo order whose durable leg identity does not match."""
        expected_trigger = (
            position.stop_loss
            if order_type is OrderType.STOP_MARKET
            else position.take_profit
        )
        if (
            order.client_order_id != client_id
            or order.symbol.upper() != position.symbol.upper()
            or order.side
            is not LivePositionProtectionService._closing_side(position.side)
            or order.order_type is not order_type
            or order.quantity < position.quantity
            or order.stop_price is None
            or expected_trigger is None
            or order.stop_price != expected_trigger
        ):
            raise RuntimeError("Reconciled protection order does not match its leg")

    @staticmethod
    def _validate_reconciled_leg(
        *,
        order: Order,
        position: Position,
        order_type: OrderType,
        client_id: str,
    ) -> None:
        """Require an exact matching protection leg that is still active."""
        LivePositionProtectionService._validate_reconciled_leg_identity(
            order=order,
            position=position,
            order_type=order_type,
            client_id=client_id,
        )
        if order.status is not OrderStatus.NEW:
            raise RuntimeError("Reconciled protection order does not match its leg")

    @staticmethod
    def _require_client_id(client_id: str | None) -> str:
        """Return a persisted protection identity before the outbound mutation."""
        if client_id is None:
            raise RuntimeError("Protection client identity was not persisted")
        return client_id

    @staticmethod
    def _with_missing_client_algo_ids(
        *,
        position: Position,
        needs_stop_loss: bool,
        needs_take_profit: bool,
    ) -> Position:
        """Assign each newly-created logical protection leg its stable identity."""
        return replace(
            position,
            stop_loss_client_algo_id=(
                position.stop_loss_client_algo_id
                if not needs_stop_loss or position.stop_loss_client_algo_id is not None
                else Position.create_stop_loss_client_algo_id()
            ),
            take_profit_client_algo_id=(
                position.take_profit_client_algo_id
                if not needs_take_profit
                or position.take_profit_client_algo_id is not None
                else Position.create_take_profit_client_algo_id()
            ),
        )

    @staticmethod
    def _find_protection_order(
        *,
        orders: Sequence[Order],
        position: Position,
        order_type: OrderType,
    ) -> Order | None:
        """Find matching protection and reject insufficient quantity coverage."""
        closing_side = LivePositionProtectionService._closing_side(position.side)
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

    @staticmethod
    def _closing_side(side: PositionSide) -> OrderSide:
        """Return the reduce-only order side for a position."""
        return OrderSide.SELL if side is PositionSide.LONG else OrderSide.BUY
