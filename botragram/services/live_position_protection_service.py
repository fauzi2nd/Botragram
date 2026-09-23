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
    ExchangeError,
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Order, Position
from botragram.repositories import PositionRepository

__all__ = ["LivePositionProtectionService"]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_RECONCILIATION_MAX_ATTEMPTS: Final[int] = 2
_RECONCILIATION_DELAY_SECONDS: Final[float] = 0.05
_PROTECTION_VISIBILITY_ATTEMPTS: Final[int] = 5
_PROTECTION_VISIBILITY_DELAY_SECONDS: Final[float] = 0.2
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
        reference_price = await self.exchange_client.get_reference_price(symbol=symbol)
        normalized_stop = rules.normalize_protection_trigger(
            raw_trigger_price=stop_loss,
            position_side=position_side,
            order_type=OrderType.STOP_MARKET,
            reference_price=reference_price,
        )
        normalized_take_profit = rules.normalize_protection_trigger(
            raw_trigger_price=take_profit,
            position_side=position_side,
            order_type=OrderType.TAKE_PROFIT_MARKET,
            reference_price=reference_price,
        )
        _LOGGER.info(
            "Pre-entry protection plan verified: symbol=%s reference_price=%s "
            "stop_loss=%s take_profit=%s",
            symbol,
            reference_price,
            normalized_stop,
            normalized_take_profit,
        )

    async def ensure(self, *, position: Position) -> Position:
        """Reconcile SL/TP orders and persist their verified trigger prices.

        Raises:
            RuntimeError: If the exchange cannot prove complete protection.
        """
        position = await self._reconcile_pending_stop_replacement(
            position=position,
        )
        protection_orders = await self.exchange_client.get_open_protection_orders(
            symbol=position.symbol,
        )
        stop_order: Order | None = None
        take_profit_order: Order | None = None

        # A client identity retained from an earlier process cannot prove whether
        # its POST was never attempted or reached the exchange before a crash.
        # Resolve it first and fail closed on an unprovable outcome.  Only
        # identities created during this invocation may proceed directly to POST.
        if position.stop_loss_client_algo_id is not None:
            adopted_stop = (
                self._find_adopted_protection_order(
                    orders=protection_orders,
                    position=position,
                    order_type=OrderType.STOP_MARKET,
                    adopted_client_id=position.stop_loss_client_algo_id,
                )
                if position.stop_loss_client_algo_id.startswith("adopted-")
                else None
            )
            if adopted_stop is not None:
                stop_order = adopted_stop
            else:
                persisted_stop, stop_conflict = await self._recover_persisted_leg(
                    position=position,
                    order_type=OrderType.STOP_MARKET,
                    client_id=position.stop_loss_client_algo_id,
                    allow_canceled=True,
                )
                if (
                    persisted_stop is not None
                    and persisted_stop.status is OrderStatus.CANCELED
                ):
                    adopted = await self._adopt_canceled_stop_replacement(
                        position=position,
                        canceled_order=persisted_stop,
                    )
                    if adopted is not None:
                        position, stop_order = adopted
                    else:
                        position = replace(
                            position,
                            stop_loss_client_algo_id=None,
                            pending_stop_loss=None,
                            pending_stop_loss_client_algo_id=None,
                            pending_protection_step=0,
                        )
                        stop_order = None
                elif stop_conflict:
                    position = replace(
                        position,
                        stop_loss_client_algo_id=None,
                    )
                    stop_order = None
                else:
                    stop_order = persisted_stop
        elif position.stop_loss is not None:
            candidate_stop = self._find_protection_order(
                orders=protection_orders,
                position=position,
                order_type=OrderType.STOP_MARKET,
            )
            if (
                candidate_stop is not None
                and candidate_stop.stop_price == position.stop_loss
            ):
                stop_order = candidate_stop

        if position.take_profit_client_algo_id is not None:
            adopted_tp = (
                self._find_adopted_protection_order(
                    orders=protection_orders,
                    position=position,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                    adopted_client_id=position.take_profit_client_algo_id,
                )
                if position.take_profit_client_algo_id.startswith("adopted-")
                else None
            )
            if adopted_tp is not None:
                take_profit_order = adopted_tp
            else:
                persisted_tp, tp_conflict = await self._recover_persisted_leg(
                    position=position,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                    client_id=position.take_profit_client_algo_id,
                    allow_canceled=True,
                )
                if (
                    persisted_tp is not None
                    and persisted_tp.status is OrderStatus.CANCELED
                ):
                    position = replace(
                        position,
                        take_profit_client_algo_id=None,
                    )
                    take_profit_order = None
                elif tp_conflict:
                    position = replace(
                        position,
                        take_profit_client_algo_id=None,
                    )
                    take_profit_order = None
                else:
                    take_profit_order = persisted_tp
        elif position.take_profit is not None:
            candidate_tp = self._find_protection_order(
                orders=protection_orders,
                position=position,
                order_type=OrderType.TAKE_PROFIT_MARKET,
            )
            if (
                candidate_tp is not None
                and candidate_tp.stop_price == position.take_profit
            ):
                take_profit_order = candidate_tp

        closing_side = self._closing_side(position.side)

        # Adopt valid manual stop loss or take profit matching planned triggers
        planned_stop: Decimal | None = None
        planned_tp: Decimal | None = None
        if stop_order is None or take_profit_order is None:
            planned_stop, planned_tp = await self._normalize_missing_protection_plan(
                position=position,
                needs_stop_loss=stop_order is None,
                needs_take_profit=take_profit_order is None,
            )

        if stop_order is None and planned_stop is not None:
            ref_price = await self.exchange_client.get_reference_price(
                symbol=position.symbol
            )
            adoptable_stop = self._find_adoptable_protection_order(
                orders=protection_orders,
                position=position,
                order_types={OrderType.STOP_MARKET, OrderType.STOP},
                reference_price=ref_price,
                is_stop_loss=True,
                expected_trigger=planned_stop,
            )
            if adoptable_stop is not None:
                adopted_stop_id = (
                    adoptable_stop.client_order_id
                    if adoptable_stop.client_order_id
                    else f"adopted-{adoptable_stop.order_id}"
                )
                _LOGGER.info(
                    "Adopting valid manual/external STOP order from venue: "
                    "symbol=%s order_id=%s client_id=%s trigger=%s",
                    position.symbol,
                    adoptable_stop.order_id,
                    adopted_stop_id,
                    adoptable_stop.stop_price,
                )
                stop_order = adoptable_stop
                position = replace(
                    position,
                    stop_loss=adoptable_stop.stop_price,
                    stop_loss_client_algo_id=adopted_stop_id,
                )
                await self.position_repository.save(position=position)

        if take_profit_order is None and planned_tp is not None:
            ref_price = await self.exchange_client.get_reference_price(
                symbol=position.symbol
            )
            adoptable_tp = self._find_adoptable_protection_order(
                orders=protection_orders,
                position=position,
                order_types={OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT},
                reference_price=ref_price,
                is_stop_loss=False,
                expected_trigger=planned_tp,
            )
            if adoptable_tp is not None:
                adopted_tp_id = (
                    adoptable_tp.client_order_id
                    if adoptable_tp.client_order_id
                    else f"adopted-{adoptable_tp.order_id}"
                )
                _LOGGER.info(
                    "Adopting valid manual/external TAKE_PROFIT order from venue: "
                    "symbol=%s order_id=%s client_id=%s trigger=%s",
                    position.symbol,
                    adoptable_tp.order_id,
                    adopted_tp_id,
                    adoptable_tp.stop_price,
                )
                take_profit_order = adoptable_tp
                position = replace(
                    position,
                    take_profit=adoptable_tp.stop_price,
                    take_profit_client_algo_id=adopted_tp_id,
                )
                await self.position_repository.save(position=position)

        for order in protection_orders:
            if order.symbol.upper() != position.symbol.upper():
                continue
            if order.status is not OrderStatus.NEW:
                continue

            if order.side is not closing_side:
                _LOGGER.warning(
                    "Canceling dangerous wrong-side protection order on venue: "
                    "symbol=%s order_id=%s side=%s (expected closing=%s)",
                    position.symbol,
                    order.order_id,
                    order.side.value,
                    closing_side.value,
                )
                await self._cancel_superfluous_protection_order(
                    symbol=position.symbol,
                    order=order,
                )
                continue

            is_owned_stop = (
                position.stop_loss_client_algo_id is not None
                and order.client_order_id == position.stop_loss_client_algo_id
                and order.order_type in (OrderType.STOP_MARKET, OrderType.STOP)
            )
            is_owned_tp = (
                position.take_profit_client_algo_id is not None
                and order.client_order_id == position.take_profit_client_algo_id
                and order.order_type
                in (OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT)
            )
            is_adopted_stop = stop_order is not None and (
                order.order_id == stop_order.order_id
                or (
                    bool(stop_order.client_order_id)
                    and order.client_order_id == stop_order.client_order_id
                )
            )
            is_adopted_tp = take_profit_order is not None and (
                order.order_id == take_profit_order.order_id
                or (
                    bool(take_profit_order.client_order_id)
                    and order.client_order_id == take_profit_order.client_order_id
                )
            )
            is_replacement_stop = Position.is_generated_stop_loss_client_algo_id(
                order.client_order_id
            )
            is_replacement_tp = Position.is_generated_take_profit_client_algo_id(
                order.client_order_id
            )
            if not (
                is_owned_stop
                or is_owned_tp
                or is_adopted_stop
                or is_adopted_tp
                or is_replacement_stop
                or is_replacement_tp
            ):
                _LOGGER.info(
                    "Canceling superfluous duplicate protection order on venue: "
                    "symbol=%s order_id=%s client_id=%s type=%s",
                    position.symbol,
                    order.order_id,
                    order.client_order_id,
                    order.order_type.value,
                )
                await self._cancel_superfluous_protection_order(
                    symbol=position.symbol,
                    order=order,
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
                try:
                    await self._submit_missing_leg(
                        position=position,
                        order_type=OrderType.STOP_MARKET,
                        trigger_price=normalized_stop,
                        client_id=self._require_client_id(
                            position.stop_loss_client_algo_id
                        ),
                    )
                except ExchangeOrderRejectedError as error:
                    _LOGGER.warning(
                        "Stop order rejected by venue (%s); refreshing mark "
                        "price and retrying",
                        error,
                    )
                    fresh_rules = await self.exchange_client.get_market_entry_rules(
                        symbol=position.symbol
                    )
                    fresh_reference = await self.exchange_client.get_reference_price(
                        symbol=position.symbol
                    )
                    clamped_stop = (
                        max(
                            fresh_rules.minimum_price,
                            fresh_reference - fresh_rules.price_tick_size * 2,
                        )
                        if position.side is PositionSide.LONG
                        else (
                            min(
                                fresh_rules.maximum_price,
                                fresh_reference + fresh_rules.price_tick_size * 2,
                            )
                            if fresh_rules.maximum_price > _DECIMAL_ZERO
                            else fresh_reference + fresh_rules.price_tick_size * 2
                        )
                    )
                    fresh_stop = fresh_rules.normalize_protection_trigger(
                        raw_trigger_price=clamped_stop,
                        position_side=position.side,
                        order_type=OrderType.STOP_MARKET,
                        reference_price=fresh_reference,
                    )
                    position = replace(position, stop_loss=fresh_stop)
                    await self.position_repository.save(position=position)
                    await self._submit_missing_leg(
                        position=position,
                        order_type=OrderType.STOP_MARKET,
                        trigger_price=fresh_stop,
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

    async def _reconcile_pending_stop_replacement(
        self,
        *,
        position: Position,
    ) -> Position:
        """Recover an interrupted stepped STOP without losing current ownership."""
        pending_id = position.pending_stop_loss_client_algo_id
        if pending_id is None:
            return position

        pending_stop = position.pending_stop_loss
        if pending_stop is None:
            raise RuntimeError("Pending LIVE STOP identity is missing its trigger")

        try:
            order = await self.exchange_client.get_protection_order_by_client_id(
                symbol=position.symbol,
                client_id=pending_id,
            )
        except ExchangeOrderNotFoundError:
            return position
        except ExchangeOrderOutcomeUnknownError as error:
            raise RuntimeError(
                "Pending LIVE STOP identity could not be verified"
            ) from error

        self._validate_pending_stop_replacement(
            order=order,
            position=position,
        )
        if order.status in {
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }:
            cleared = replace(
                position,
                pending_stop_loss=None,
                pending_stop_loss_client_algo_id=None,
                pending_protection_step=0,
            )
            await self.position_repository.save(position=cleared)
            return cleared
        if order.status is OrderStatus.FILLED:
            raise RuntimeError(
                "Pending LIVE STOP is filled while exchange position remains active"
            )
        if order.status is not OrderStatus.NEW:
            raise RuntimeError("Pending LIVE STOP is neither active nor terminal")

        target = await self.exchange_client.ensure_stop_loss_order(
            symbol=position.symbol,
            side=self._closing_side(position.side),
            quantity=position.quantity,
            stop_loss=pending_stop,
            client_algo_id=pending_id,
            previous_client_algo_id=position.stop_loss_client_algo_id,
        )
        self._validate_pending_stop_replacement(
            order=target,
            position=position,
        )
        if target.status is not OrderStatus.NEW:
            raise RuntimeError("Recovered pending LIVE STOP is not active")

        promoted = replace(
            position,
            stop_loss=pending_stop,
            stop_loss_client_algo_id=pending_id,
            protection_step=position.pending_protection_step,
            pending_stop_loss=None,
            pending_stop_loss_client_algo_id=None,
            pending_protection_step=0,
        )
        await self.position_repository.save(position=promoted)
        _LOGGER.info(
            "Pending LIVE STOP replacement recovered: symbol=%s step=%d",
            promoted.symbol,
            promoted.protection_step,
        )
        return promoted

    @staticmethod
    def _validate_pending_stop_replacement(
        *,
        order: Order,
        position: Position,
    ) -> None:
        """Require exact pending STOP identity and immutable replacement shape."""
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
        reference_price = await self.exchange_client.get_reference_price(
            symbol=position.symbol
        )

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
            if position.stop_loss is not None:
                if (
                    position.side is PositionSide.LONG
                    and stop_source >= reference_price
                ):
                    stop_source = max(
                        rules.minimum_price,
                        reference_price - rules.price_tick_size,
                    )
                elif (
                    position.side is PositionSide.SHORT
                    and stop_source <= reference_price
                ):
                    stop_source = (
                        min(
                            rules.maximum_price,
                            reference_price + rules.price_tick_size,
                        )
                        if rules.maximum_price > _DECIMAL_ZERO
                        else reference_price + rules.price_tick_size
                    )
            normalized_stop = rules.normalize_protection_trigger(
                raw_trigger_price=stop_source,
                position_side=position.side,
                order_type=OrderType.STOP_MARKET,
                reference_price=reference_price,
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
            if position.take_profit is not None:
                if (
                    position.side is PositionSide.LONG
                    and take_profit_source <= reference_price
                ):
                    take_profit_source = (
                        min(
                            rules.maximum_price,
                            reference_price + rules.price_tick_size,
                        )
                        if rules.maximum_price > _DECIMAL_ZERO
                        else reference_price + rules.price_tick_size
                    )
                elif (
                    position.side is PositionSide.SHORT
                    and take_profit_source >= reference_price
                ):
                    take_profit_source = max(
                        rules.minimum_price,
                        reference_price - rules.price_tick_size,
                    )
            normalized_take_profit = rules.normalize_protection_trigger(
                raw_trigger_price=take_profit_source,
                position_side=position.side,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                reference_price=reference_price,
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

        return await self._wait_for_verified_leg(
            position=position,
            order_type=order_type,
            client_id=client_id,
        )

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
        await self._wait_for_verified_leg(
            position=position,
            order_type=order_type,
            client_id=client_id,
        )

    async def _wait_for_verified_leg(
        self,
        *,
        position: Position,
        order_type: OrderType,
        client_id: str,
    ) -> Order:
        """Wait briefly for an accepted protection order to become queryable."""
        last_unknown: ExchangeOrderOutcomeUnknownError | None = None
        for attempt in range(_PROTECTION_VISIBILITY_ATTEMPTS):
            try:
                order = await self.exchange_client.get_protection_order_by_client_id(
                    symbol=position.symbol,
                    client_id=client_id,
                )
            except ExchangeOrderNotFoundError:
                _LOGGER.debug(
                    "Protection order %s for %s not yet visible (attempt %d/%d)",
                    client_id,
                    position.symbol,
                    attempt + 1,
                    _PROTECTION_VISIBILITY_ATTEMPTS,
                )
            except ExchangeOrderOutcomeUnknownError as error:
                last_unknown = error
            else:
                self._validate_reconciled_leg(
                    order=order,
                    position=position,
                    order_type=order_type,
                    client_id=client_id,
                )
                return order

            if attempt + 1 < _PROTECTION_VISIBILITY_ATTEMPTS:
                await asyncio.sleep(_PROTECTION_VISIBILITY_DELAY_SECONDS)

        if last_unknown is not None:
            raise RuntimeError(
                "Submitted protection identity could not be verified"
            ) from last_unknown
        raise RuntimeError("Exchange did not confirm submitted protection identity")

    async def _recover_persisted_leg(
        self,
        *,
        position: Position,
        order_type: OrderType,
        client_id: str,
        allow_canceled: bool = False,
    ) -> tuple[Order | None, bool]:
        """Prove a pre-restart protection mutation through one authoritative GET.

        A transport-uncertain result remains terminal for this recovery pass.
        An authoritative not-found result returns ``(None, False)`` so the caller
        may recreate the same durable identity. A type-mismatched or wrong-side
        order returns ``(None, True)`` signaling that the ID is occupied by a
        conflicting order and a fresh identity must be generated.

        Returns:
            A tuple of (matching_order, is_id_conflict).
        """
        last_unknown: ExchangeOrderOutcomeUnknownError | None = None
        for attempt in range(_PROTECTION_VISIBILITY_ATTEMPTS):
            try:
                order = await self.exchange_client.get_protection_order_by_client_id(
                    symbol=position.symbol,
                    client_id=client_id,
                )
            except ExchangeOrderNotFoundError:
                _LOGGER.debug(
                    "Recovering protection leg %s for %s not yet visible "
                    "(attempt %d/%d)",
                    client_id,
                    position.symbol,
                    attempt + 1,
                    _PROTECTION_VISIBILITY_ATTEMPTS,
                )
            except ExchangeOrderOutcomeUnknownError as error:
                last_unknown = error
            else:
                expected_types = (
                    {OrderType.STOP_MARKET, OrderType.STOP}
                    if order_type in (OrderType.STOP_MARKET, OrderType.STOP)
                    else {OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT}
                )
                closing_side = self._closing_side(position.side)
                if (
                    order.symbol.upper() != position.symbol.upper()
                    or order.side is not closing_side
                    or order.order_type not in expected_types
                ):
                    _LOGGER.warning(
                        "Protection order candidate %r does not match expected leg "
                        "(symbol=%s side=%s type=%s; got symbol=%s side=%s type=%s); "
                        "treating leg as absent and regenerating client ID",
                        client_id,
                        position.symbol,
                        closing_side.value,
                        order_type.value,
                        order.symbol,
                        order.side.value,
                        order.order_type.value,
                    )
                    return (None, True)

                self._validate_reconciled_leg_identity(
                    order=order,
                    position=position,
                    order_type=order_type,
                    client_id=client_id,
                )
                if order.status is OrderStatus.NEW or (
                    allow_canceled and order.status is OrderStatus.CANCELED
                ):
                    return (order, False)
                raise RuntimeError("Reconciled protection order does not match its leg")

            if attempt + 1 < _PROTECTION_VISIBILITY_ATTEMPTS:
                await asyncio.sleep(_PROTECTION_VISIBILITY_DELAY_SECONDS)

        if last_unknown is not None:
            raise RuntimeError(
                "Persisted LIVE protection identity could not be verified"
            ) from last_unknown

        _LOGGER.warning(
            "Persisted LIVE protection identity is absent after bounded "
            "visibility checks; the same durable identity may be recreated "
            "after fresh venue validation: symbol=%s type=%s client_id=%s",
            position.symbol,
            order_type.value,
            client_id,
        )
        return (None, False)

    async def _adopt_canceled_stop_replacement(
        self,
        *,
        position: Position,
        canceled_order: Order,
    ) -> tuple[Position, Order] | None:
        """Persist one uniquely proven Botragram stepped STOP replacement.

        The predecessor's exact durable identity must already be proven
        canceled. Recovery performs only a fresh open-order GET and a local
        durable save; it never submits or cancels an exchange order.
        """
        if canceled_order.status is not OrderStatus.CANCELED:
            raise RuntimeError("Persisted LIVE STOP predecessor is not canceled")

        open_orders = await self.exchange_client.get_open_protection_orders(
            symbol=position.symbol,
        )
        replacement = self._find_owned_active_stop_replacement(
            orders=open_orders,
            position=position,
            canceled_client_id=canceled_order.client_order_id,
        )
        if replacement is None:
            return None

        replacement_id = replacement.client_order_id
        replacement_stop = replacement.stop_price
        if replacement_id is None or replacement_stop is None:
            raise RuntimeError("Recovered LIVE STOP replacement is incomplete")

        adopted = replace(
            position,
            stop_loss=replacement_stop,
            stop_loss_client_algo_id=replacement_id,
        )
        await self.position_repository.save(position=adopted)
        _LOGGER.warning(
            "Canceled persisted LIVE STOP replaced by unique active Botragram "
            "STOP; durable ownership recovered: symbol=%s old_client_id=%s "
            "new_client_id=%s stop_loss=%s",
            adopted.symbol,
            canceled_order.client_order_id,
            replacement_id,
            replacement_stop,
        )
        return adopted, replacement

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

        expected_types = (
            {OrderType.STOP_MARKET, OrderType.STOP}
            if order_type in (OrderType.STOP_MARKET, OrderType.STOP)
            else {OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT}
        )
        closing_side = self._closing_side(position.side)
        if (
            order.symbol.upper() != position.symbol.upper()
            or order.side is not closing_side
            or order.order_type not in expected_types
        ):
            _LOGGER.debug(
                "Protection order probe %r returned order of type %s; "
                "expected leg %s is absent on venue",
                client_id,
                order.order_type.value,
                order_type.value,
            )
            return "not_found"

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
            if order_type in (OrderType.STOP_MARKET, OrderType.STOP)
            else position.take_profit
        )
        expected_types = (
            {OrderType.STOP_MARKET, OrderType.STOP}
            if order_type in (OrderType.STOP_MARKET, OrderType.STOP)
            else {OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT}
        )
        closing_side = LivePositionProtectionService._closing_side(position.side)
        mismatches: list[str] = []
        if order.client_order_id != client_id:
            mismatches.append(
                f"client_order_id={order.client_order_id!r} != {client_id!r}"
            )
        if order.symbol.upper() != position.symbol.upper():
            mismatches.append(f"symbol={order.symbol!r} != {position.symbol!r}")
        if order.side is not closing_side:
            mismatches.append(f"side={order.side!r} != expected={closing_side!r}")
        type_mismatch = order.order_type not in expected_types
        if type_mismatch:
            mismatches.append(
                f"order_type={order.order_type!r} not in {expected_types!r}"
            )
        if order.quantity > _DECIMAL_ZERO and order.quantity < position.quantity:
            mismatches.append(
                f"quantity={order.quantity} < position.quantity={position.quantity}"
            )
        if order.stop_price is None:
            mismatches.append("stop_price=None")
        if expected_trigger is None:
            mismatches.append(
                f"expected_trigger=None (position sl/tp not set for {order_type!r})"
            )
        if order.stop_price is not None and expected_trigger is not None:
            if order.stop_price != expected_trigger:
                mismatches.append(
                    f"stop_price={order.stop_price} "
                    f"!= expected_trigger={expected_trigger}"
                )
        if mismatches:
            _LOGGER.warning(
                "Protection order identity mismatch: %s | "
                "order_id=%s client_id=%s order_type=%s "
                "order_qty=%s pos_qty=%s stop_price=%s expected_trigger=%s",
                "; ".join(mismatches),
                order.order_id,
                order.client_order_id,
                order.order_type,
                order.quantity,
                position.quantity,
                order.stop_price,
                expected_trigger,
            )
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
                continue

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
    def _find_adopted_protection_order(
        *,
        orders: Sequence[Order],
        position: Position,
        order_type: OrderType,
        adopted_client_id: str,
    ) -> Order | None:
        """Return an active adopted protection order matching its durable identity."""
        if not adopted_client_id.startswith("adopted-"):
            return None
        target_order_id = adopted_client_id.removeprefix("adopted-")
        closing_side = LivePositionProtectionService._closing_side(position.side)
        expected_types = (
            {OrderType.STOP_MARKET, OrderType.STOP}
            if order_type in (OrderType.STOP_MARKET, OrderType.STOP)
            else {OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT}
        )
        for order in orders:
            if (
                order.symbol.upper() == position.symbol.upper()
                and order.side is closing_side
                and order.order_type in expected_types
                and (
                    order.order_id == target_order_id
                    or order.client_order_id == adopted_client_id
                    or f"adopted-{order.order_id}" == adopted_client_id
                )
            ):
                return replace(order, client_order_id=adopted_client_id)
        return None

    @staticmethod
    def _find_adoptable_protection_order(
        *,
        orders: Sequence[Order],
        position: Position,
        order_types: set[OrderType],
        reference_price: Decimal,
        is_stop_loss: bool,
        expected_trigger: Decimal | None = None,
    ) -> Order | None:
        """Find the best valid external/manual protection order on venue."""
        closing_side = LivePositionProtectionService._closing_side(position.side)
        candidates: list[Order] = []

        for order in orders:
            if (
                order.symbol.upper() != position.symbol.upper()
                or order.side is not closing_side
                or order.order_type not in order_types
                or order.status is not OrderStatus.NEW
                or order.stop_price is None
                or order.stop_price <= _DECIMAL_ZERO
            ):
                continue

            if order.quantity < position.quantity:
                continue

            trigger = order.stop_price
            if expected_trigger is not None and trigger != expected_trigger:
                continue

            if is_stop_loss:
                if position.side is PositionSide.LONG and trigger >= reference_price:
                    continue
                if position.side is PositionSide.SHORT and trigger <= reference_price:
                    continue
            else:
                if position.side is PositionSide.LONG and trigger <= reference_price:
                    continue
                if position.side is PositionSide.SHORT and trigger >= reference_price:
                    continue

            candidates.append(order)

        if not candidates:
            return None

        if is_stop_loss:
            return (
                max(candidates, key=lambda o: o.stop_price or _DECIMAL_ZERO)
                if position.side is PositionSide.LONG
                else min(candidates, key=lambda o: o.stop_price or _DECIMAL_ZERO)
            )

        return (
            min(candidates, key=lambda o: o.stop_price or _DECIMAL_ZERO)
            if position.side is PositionSide.LONG
            else max(candidates, key=lambda o: o.stop_price or _DECIMAL_ZERO)
        )

    async def _cancel_superfluous_protection_order(
        self,
        *,
        symbol: str,
        order: Order,
    ) -> None:
        """Cancel an extra or invalid protection order on venue safely."""
        try:
            await self.exchange_client.cancel_order(
                symbol=symbol,
                order_id=order.order_id,
            )
            return
        except asyncio.CancelledError:
            raise
        except (
            ExchangeError,
            ExchangeOrderNotFoundError,
            RuntimeError,
            ValueError,
        ) as error:
            _LOGGER.debug(
                "Primary order cancellation failed for %s (%s): %s; "
                "falling back to client_id",
                order.order_id,
                symbol,
                error,
            )

        client_id = order.client_order_id
        order_id = order.order_id
        if client_id or order_id:
            try:
                await self.exchange_client.cancel_protection_order(
                    symbol=symbol,
                    client_id=client_id,
                    order_id=order_id,
                )
            except Exception as error:
                _LOGGER.warning(
                    "Failed to cancel superfluous protection order: "
                    "symbol=%s order_id=%s error=%s",
                    symbol,
                    order.order_id,
                    error,
                )

    @staticmethod
    def _find_owned_active_stop_replacement(
        *,
        orders: Sequence[Order],
        position: Position,
        canceled_client_id: str | None,
    ) -> Order | None:
        """Return one authoritative Botragram stepped STOP or fail closed."""
        candidates = tuple(
            order
            for order in orders
            if order.client_order_id != canceled_client_id
            and Position.is_generated_stop_loss_client_algo_id(order.client_order_id)
            and order.symbol.upper() == position.symbol.upper()
            and order.side is LivePositionProtectionService._closing_side(position.side)
            and order.order_type is OrderType.STOP_MARKET
            and order.status is OrderStatus.NEW
            and order.quantity == position.quantity
            and LivePositionProtectionService._is_tighter_stepped_stop(
                position=position,
                stop_price=order.stop_price,
            )
        )
        if len(candidates) > 1:
            raise RuntimeError(
                "Canceled persisted LIVE STOP has no unique active Botragram "
                "replacement"
            )
        if not candidates:
            return None
        return candidates[0]

    @staticmethod
    def _is_tighter_stepped_stop(
        *,
        position: Position,
        stop_price: Decimal | None,
    ) -> bool:
        """Require a replacement inside Entry-to-TP and tighter than current."""
        current_stop = position.stop_loss
        take_profit = position.take_profit
        if stop_price is None or current_stop is None or take_profit is None:
            return False
        if position.side is PositionSide.LONG:
            return current_stop < stop_price and (
                position.entry_price < stop_price < take_profit
            )
        return stop_price < current_stop and (
            take_profit < stop_price < position.entry_price
        )

    @staticmethod
    def _closing_side(side: PositionSide) -> OrderSide:
        """Return the reduce-only order side for a position."""
        return OrderSide.SELL if side is PositionSide.LONG else OrderSide.BUY
