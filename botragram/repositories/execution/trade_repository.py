"""
Botragram

Description:
    Executed trade repository interface.

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
from botragram.enums import OrderSide
from botragram.models import Trade

__all__ = [
    "TradeRepository",
]


# =============================================================================
# Abstract Repositories
# =============================================================================
class TradeRepository(ABC):
    """Abstract persistence interface for executed trades."""

    __slots__ = ()

    @abstractmethod
    async def save(
        self,
        *,
        trade: Trade,
    ) -> None:
        """Persist an executed trade.

        Args:
            trade: Executed trade to persist.
        """

    @abstractmethod
    async def save_many(
        self,
        *,
        trades: Sequence[Trade],
    ) -> None:
        """Persist multiple executed trades.

        Args:
            trades: Executed trades to persist.
        """

    @abstractmethod
    async def get_by_id(
        self,
        *,
        trade_id: str,
        symbol: str | None = None,
    ) -> Trade | None:
        """Return a trade by identifier.

        Args:
            trade_id: Exchange trade identifier.
            symbol: Optional trading symbol filter.

        Returns:
            Matching trade, or None when it does not exist.
        """

    @abstractmethod
    async def get_by_order_id(
        self,
        *,
        order_id: str,
        symbol: str | None = None,
    ) -> Sequence[Trade]:
        """Return all fills associated with an order.

        Args:
            order_id: Exchange order identifier.
            symbol: Optional trading symbol filter.

        Returns:
            Matching trades ordered from oldest to newest.
        """

    @abstractmethod
    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        side: OrderSide | None = None,
    ) -> Sequence[Trade]:
        """Return the latest executed trades.

        Args:
            limit: Maximum number of trades to return.
            symbol: Optional trading symbol filter.
            side: Optional order-side filter.

        Returns:
            Matching trades ordered from oldest to newest.
        """

    @abstractmethod
    async def get_between(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        symbol: str | None = None,
        side: OrderSide | None = None,
    ) -> Sequence[Trade]:
        """Return trades executed within a datetime range.

        Args:
            start_time: Inclusive execution-time boundary.
            end_time: Inclusive execution-time boundary.
            symbol: Optional trading symbol filter.
            side: Optional order-side filter.

        Returns:
            Matching trades ordered from oldest to newest.
        """

    @abstractmethod
    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
    ) -> int:
        """Delete trades older than a datetime boundary.

        Args:
            before: Exclusive deletion boundary.
            symbol: Optional trading symbol filter.

        Returns:
            Number of deleted trade records.
        """

    @abstractmethod
    async def count(
        self,
        *,
        symbol: str | None = None,
        side: OrderSide | None = None,
    ) -> int:
        """Count stored executed trades.

        Args:
            symbol: Optional trading symbol filter.
            side: Optional order-side filter.

        Returns:
            Number of matching trade records.
        """
