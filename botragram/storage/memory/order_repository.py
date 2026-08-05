"""
Botragram

Description:
    In-memory trading order repository implementation.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
import asyncio
from collections.abc import Sequence
from datetime import datetime

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OrderSide, OrderStatus, OrderType
from botragram.models import Order
from botragram.repositories import OrderRepository

__all__ = [
    "MemoryOrderRepository",
]


# =============================================================================
# Type Aliases
# =============================================================================
type OrderKey = tuple[str, str]


# =============================================================================
# Repository Implementations
# =============================================================================
class MemoryOrderRepository(OrderRepository):
    """Store trading orders in process memory."""

    __slots__ = (
        "_lock",
        "_orders",
    )

    def __init__(self) -> None:
        """Initialize an empty order repository."""
        self._orders: dict[OrderKey, Order] = {}
        self._lock = asyncio.Lock()

    async def save(
        self,
        *,
        order: Order,
    ) -> None:
        """Persist or replace a trading order."""
        key = self._create_key(order)

        async with self._lock:
            self._orders[key] = order

    async def save_many(
        self,
        *,
        orders: Sequence[Order],
    ) -> None:
        """Persist or replace multiple trading orders."""
        records: dict[OrderKey, Order] = {
            self._create_key(order): order for order in orders
        }

        async with self._lock:
            self._orders.update(records)

    async def get_by_id(
        self,
        *,
        order_id: str,
        symbol: str | None = None,
    ) -> Order | None:
        """Return an order by identifier."""
        normalized_order_id = self._normalize_order_id(order_id)

        if symbol is not None:
            key: OrderKey = (
                self._normalize_symbol(symbol),
                normalized_order_id,
            )

            async with self._lock:
                return self._orders.get(key)

        async with self._lock:
            matching_order: Order | None = None

            for order in self._orders.values():
                if order.order_id != normalized_order_id:
                    continue

                if matching_order is not None:
                    raise RuntimeError(
                        f"Multiple orders use identifier {normalized_order_id!r}"
                    )

                matching_order = order

        return matching_order

    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        side: OrderSide | None = None,
        order_type: OrderType | None = None,
        status: OrderStatus | None = None,
    ) -> Sequence[Order]:
        """Return the latest trading orders."""
        if limit <= 0:
            raise ValueError("Order limit must be greater than zero")

        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            orders: list[Order] = [
                order
                for order in self._orders.values()
                if self._matches(
                    order=order,
                    symbol=normalized_symbol,
                    side=side,
                    order_type=order_type,
                    status=status,
                )
            ]

        orders.sort(key=lambda order: order.created_at)

        return tuple(orders[-limit:])

    async def get_between(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        symbol: str | None = None,
        side: OrderSide | None = None,
        order_type: OrderType | None = None,
        status: OrderStatus | None = None,
    ) -> Sequence[Order]:
        """Return orders created within an inclusive datetime range."""
        if start_time > end_time:
            raise ValueError("Order start time must not be after end time")

        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            orders: list[Order] = [
                order
                for order in self._orders.values()
                if (
                    start_time <= order.created_at <= end_time
                    and self._matches(
                        order=order,
                        symbol=normalized_symbol,
                        side=side,
                        order_type=order_type,
                        status=status,
                    )
                )
            ]

        orders.sort(key=lambda order: order.created_at)

        return tuple(orders)

    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open orders."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            orders: list[Order] = [
                order
                for order in self._orders.values()
                if (
                    (
                        normalized_symbol is None
                        or order.symbol.upper() == normalized_symbol
                    )
                    and self._is_open_status(order.status)
                )
            ]

        orders.sort(key=lambda order: order.created_at)

        return tuple(orders)

    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
    ) -> int:
        """Delete orders older than a datetime boundary."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            keys_to_delete: tuple[OrderKey, ...] = tuple(
                key
                for key, order in self._orders.items()
                if (
                    order.created_at < before
                    and (
                        normalized_symbol is None
                        or order.symbol.upper() == normalized_symbol
                    )
                )
            )

            for key in keys_to_delete:
                del self._orders[key]

        return len(keys_to_delete)

    async def count(
        self,
        *,
        symbol: str | None = None,
        side: OrderSide | None = None,
        order_type: OrderType | None = None,
        status: OrderStatus | None = None,
    ) -> int:
        """Count stored trading orders."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            return sum(
                1
                for order in self._orders.values()
                if self._matches(
                    order=order,
                    symbol=normalized_symbol,
                    side=side,
                    order_type=order_type,
                    status=status,
                )
            )

    @staticmethod
    def _create_key(
        order: Order,
    ) -> OrderKey:
        """Create a unique in-memory order key."""
        return (
            MemoryOrderRepository._normalize_symbol(order.symbol),
            MemoryOrderRepository._normalize_order_id(order.order_id),
        )

    @staticmethod
    def _matches(
        *,
        order: Order,
        symbol: str | None,
        side: OrderSide | None,
        order_type: OrderType | None,
        status: OrderStatus | None,
    ) -> bool:
        """Return whether an order matches optional filters."""
        return (
            (symbol is None or order.symbol.upper() == symbol)
            and (side is None or order.side is side)
            and (order_type is None or order.order_type is order_type)
            and (status is None or order.status is status)
        )

    @staticmethod
    def _is_open_status(
        status: OrderStatus,
    ) -> bool:
        """Return whether an order status represents an open order."""
        return status.value in {
            "NEW",
            "PARTIALLY_FILLED",
            "PENDING_NEW",
        }

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol

    @staticmethod
    def _normalize_order_id(
        order_id: str,
    ) -> str:
        """Normalize and validate an order identifier."""
        normalized_order_id = order_id.strip()

        if not normalized_order_id:
            raise ValueError("Order identifier must not be empty")

        return normalized_order_id
