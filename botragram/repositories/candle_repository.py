"""
Botragram

Description:
    Candle repository interface.

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
from botragram.models import Candle

__all__ = [
    "CandleRepository",
]


# =============================================================================
# Abstract Repositories
# =============================================================================
class CandleRepository(ABC):
    """Abstract persistence interface for candlestick market data."""

    __slots__ = ()

    @abstractmethod
    async def save(
        self,
        *,
        candle: Candle,
    ) -> None:
        """Persist a candlestick record.

        Args:
            candle: Candle to persist.
        """

    @abstractmethod
    async def save_many(
        self,
        *,
        candles: Sequence[Candle],
    ) -> None:
        """Persist multiple candlestick records.

        Args:
            candles: Candles to persist.
        """

    @abstractmethod
    async def get_latest(
        self,
        *,
        symbol: str,
        limit: int,
    ) -> Sequence[Candle]:
        """Return the latest candles for a trading symbol.

        Args:
            symbol: Trading pair symbol.
            limit: Maximum number of candles to return.

        Returns:
            Candles ordered from oldest to newest.
        """

    @abstractmethod
    async def get_between(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Sequence[Candle]:
        """Return candles within a datetime range.

        Args:
            symbol: Trading pair symbol.
            start_time: Inclusive candle open-time boundary.
            end_time: Inclusive candle open-time boundary.

        Returns:
            Matching candles ordered from oldest to newest.
        """

    @abstractmethod
    async def get_by_open_time(
        self,
        *,
        symbol: str,
        open_time: datetime,
    ) -> Candle | None:
        """Return a candle by symbol and open time.

        Args:
            symbol: Trading pair symbol.
            open_time: Exact candle open time.

        Returns:
            Matching candle, or None when it does not exist.
        """

    @abstractmethod
    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
    ) -> int:
        """Delete candles older than a datetime boundary.

        Args:
            before: Exclusive deletion boundary.
            symbol: Optional trading symbol filter.

        Returns:
            Number of deleted candle records.
        """

    @abstractmethod
    async def count(
        self,
        *,
        symbol: str | None = None,
    ) -> int:
        """Count stored candles.

        Args:
            symbol: Optional trading symbol filter.

        Returns:
            Number of matching candle records.
        """
