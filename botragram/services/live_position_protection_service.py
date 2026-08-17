"""Reconcile and verify Futures protection for one live position."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from botragram.engine import RiskEngine
from botragram.enums import OrderSide, OrderType, PositionSide
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Order, Position
from botragram.repositories import PositionRepository

__all__ = ["LivePositionProtectionService"]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


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
        calculated_stop, calculated_take_profit = (
            self.risk_engine.calculate_protection_levels(
                side=position.side,
                entry_price=position.entry_price,
                strategy_type=position.strategy_type,
            )
        )

        if stop_order is None or take_profit_order is None:
            _LOGGER.info(
                "Live protection reconciliation started: symbol=%s missing_stop=%s "
                "missing_take_profit=%s",
                position.symbol,
                stop_order is None,
                take_profit_order is None,
            )
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
