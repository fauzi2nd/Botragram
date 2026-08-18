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


@dataclass(slots=True, kw_only=True, frozen=True)
class LivePositionProtectionService:
    """Ensure one Futures position has exchange-verified SL and TP coverage."""

    exchange_client: BaseExchangeClient
    position_repository: PositionRepository
    risk_engine: RiskEngine

    async def ensure(self, *, position: Position) -> Position:
        """Reconcile SL/TP orders and persist their verified trigger prices.

        Raises:
            RuntimeError: If the exchange cannot prove complete protection.
        """
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
            ) = await self._normalize_initial_protection_plan(position=position)
            _LOGGER.info(
                "Live protection reconciliation started: symbol=%s missing_stop=%s "
                "missing_take_profit=%s",
                position.symbol,
                stop_order is None,
                take_profit_order is None,
            )
            if stop_order is None:
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

    async def _normalize_initial_protection_plan(
        self,
        *,
        position: Position,
    ) -> tuple[Decimal, Decimal]:
        """Return the complete validated venue-trigger plan before persistence.

        Both legs are planned before a durable protection identity is created so
        local rule, mark-price, or logical validation failures have no mutation
        or persistence side effect. Persisted ``Position`` trigger fields then
        represent final venue prices, never unrounded risk-engine intent.
        """
        raw_stop, raw_take_profit = self.risk_engine.calculate_protection_levels(
            side=position.side,
            entry_price=position.entry_price,
            strategy_type=position.strategy_type,
        )
        rules = await self.exchange_client.get_market_entry_rules(
            symbol=position.symbol,
        )
        mark_price = await self.exchange_client.get_mark_price(symbol=position.symbol)
        return (
            rules.normalize_protection_trigger(
                raw_trigger_price=raw_stop,
                position_side=position.side,
                order_type=OrderType.STOP_MARKET,
                mark_price=mark_price,
            ),
            rules.normalize_protection_trigger(
                raw_trigger_price=raw_take_profit,
                position_side=position.side,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                mark_price=mark_price,
            ),
        )

    async def _get_verified_submitted_leg(
        self,
        *,
        position: Position,
        order_type: OrderType,
    ) -> Order:
        """Return the newly submitted leg only after an authoritative read."""
        orders = await self.exchange_client.get_open_protection_orders(
            symbol=position.symbol,
        )
        order = self._find_protection_order(
            orders=orders,
            position=position,
            order_type=order_type,
        )
        if order is None:
            raise RuntimeError("Exchange did not confirm submitted protection order")
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
    ) -> Order:
        """Prove a pre-restart protection mutation through one authoritative GET.

        A not-found or transport-uncertain result is deliberately terminal for
        this recovery pass: the service must not infer that it is safe to POST a
        replacement using the retained client identity.

        Args:
            position: The live position that requires protection.
            order_type: The logical protection leg to recover.
            client_id: The durable exchange client identity for that leg.

        Returns:
            The authoritative matching protection order.

        Raises:
            RuntimeError: If the protection mutation cannot be proven.
        """
        try:
            order = await self.exchange_client.get_protection_order_by_client_id(
                symbol=position.symbol,
                client_id=client_id,
            )
        except ExchangeOrderNotFoundError as error:
            raise RuntimeError(
                "Persisted LIVE protection identity was not found; refusing "
                "replacement POST"
            ) from error
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

    @staticmethod
    def _validate_reconciled_leg(
        *,
        order: Order,
        position: Position,
        order_type: OrderType,
        client_id: str,
    ) -> None:
        """Reject a queried algo order that cannot cover the expected leg."""
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
            or order.status is not OrderStatus.NEW
        ):
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
