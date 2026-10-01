"""
Botragram

Description:
    Trading order repository interface.

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
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OrderSide, OrderStatus, OrderType
from botragram.models import Order

__all__ = [
    "OrderRepository",
]


# =============================================================================
# Abstract Repositories
# =============================================================================
class OrderRepository(ABC):
    """Abstract persistence interface for trading orders."""

    __slots__ = ()

    @abstractmethod
    async def save(
        self,
        *,
        order: Order,
    ) -> None:
        """Persist a trading order.

        Args:
            order: Trading order to persist.
        """

    @abstractmethod
    async def save_many(
        self,
        *,
        orders: Sequence[Order],
    ) -> None:
        """Persist multiple trading orders.

        Args:
            orders: Trading orders to persist.
        """

    @abstractmethod
    async def get_by_id(
        self,
        *,
        order_id: str,
        symbol: str | None = None,
    ) -> Order | None:
        """Return an order by identifier.

        Args:
            order_id: Exchange order identifier.
            symbol: Optional trading symbol filter.

        Returns:
            Matching order, or None when it does not exist.
        """

    @abstractmethod
    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        side: OrderSide | None = None,
        order_type: OrderType | None = None,
        status: OrderStatus | None = None,
    ) -> Sequence[Order]:
        """Return the latest trading orders.

        Args:
            limit: Maximum number of orders to return.
            symbol: Optional trading symbol filter.
            side: Optional order-side filter.
            order_type: Optional order-type filter.
            status: Optional order-status filter.

        Returns:
            Matching orders ordered from oldest to newest.
        """

    @abstractmethod
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
        """Return orders created within a datetime range.

        Args:
            start_time: Inclusive order creation boundary.
            end_time: Inclusive order creation boundary.
            symbol: Optional trading symbol filter.
            side: Optional order-side filter.
            order_type: Optional order-type filter.
            status: Optional order-status filter.

        Returns:
            Matching orders ordered from oldest to newest.
        """

    @abstractmethod
    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open orders.

        Args:
            symbol: Optional trading symbol filter.

        Returns:
            Matching open orders ordered from oldest to newest.
        """

    @abstractmethod
    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
    ) -> int:
        """Delete orders older than a datetime boundary.

        Args:
            before: Exclusive deletion boundary.
            symbol: Optional trading symbol filter.

        Returns:
            Number of deleted order records.
        """

    @abstractmethod
    async def count(
        self,
        *,
        symbol: str | None = None,
        side: OrderSide | None = None,
        order_type: OrderType | None = None,
        status: OrderStatus | None = None,
    ) -> int:
        """Count stored trading orders.

        Args:
            symbol: Optional trading symbol filter.
            side: Optional order-side filter.
            order_type: Optional order-type filter.
            status: Optional order-status filter.

        Returns:
            Number of matching order records.
        """
