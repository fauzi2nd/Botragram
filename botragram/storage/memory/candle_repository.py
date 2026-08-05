"""
Botragram

Description:
    In-memory candle repository implementation.

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
from botragram.enums import Interval
from botragram.models import Candle
from botragram.repositories import CandleRepository

__all__ = [
    "MemoryCandleRepository",
]


# =============================================================================
# Type Aliases
# =============================================================================
type CandleKey = tuple[
    str,
    Interval,
    datetime,
]


# =============================================================================
# Repository Implementations
# =============================================================================
class MemoryCandleRepository(CandleRepository):
    """Store candlestick market data in process memory."""

    __slots__ = (
        "_candles",
        "_lock",
    )

    def __init__(self) -> None:
        """Initialize an empty candle repository."""
        self._candles: dict[CandleKey, Candle] = {}
        self._lock = asyncio.Lock()

    async def save(
        self,
        *,
        candle: Candle,
    ) -> None:
        """Persist or replace a candlestick record."""
        key = self._create_key(candle)

        async with self._lock:
            self._candles[key] = candle

    async def save_many(
        self,
        *,
        candles: Sequence[Candle],
    ) -> None:
        """Persist or replace multiple candlestick records."""
        records: dict[CandleKey, Candle] = {
            self._create_key(candle): candle for candle in candles
        }

        async with self._lock:
            self._candles.update(records)

    async def get_latest(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
    ) -> Sequence[Candle]:
        """Return the latest candles for a symbol and interval."""
        if limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        normalized_symbol = self._normalize_symbol(symbol)

        async with self._lock:
            candles: list[Candle] = [
                candle
                for candle in self._candles.values()
                if (
                    candle.symbol.upper() == normalized_symbol
                    and candle.interval is interval
                )
            ]

        candles.sort(key=lambda candle: candle.open_time)

        return tuple(candles[-limit:])

    async def get_between(
        self,
        *,
        symbol: str,
        interval: Interval,
        start_time: datetime,
        end_time: datetime,
    ) -> Sequence[Candle]:
        """Return candles within an inclusive datetime range."""
        if start_time > end_time:
            raise ValueError("Candle start time must not be after end time")

        normalized_symbol = self._normalize_symbol(symbol)

        async with self._lock:
            candles: list[Candle] = [
                candle
                for candle in self._candles.values()
                if (
                    candle.symbol.upper() == normalized_symbol
                    and candle.interval is interval
                    and start_time <= candle.open_time <= end_time
                )
            ]

        candles.sort(key=lambda candle: candle.open_time)

        return tuple(candles)

    async def get_by_open_time(
        self,
        *,
        symbol: str,
        interval: Interval,
        open_time: datetime,
    ) -> Candle | None:
        """Return a candle by symbol, interval, and open time."""
        key: CandleKey = (
            self._normalize_symbol(symbol),
            interval,
            open_time,
        )

        async with self._lock:
            return self._candles.get(key)

    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
        interval: Interval | None = None,
    ) -> int:
        """Delete candles older than a datetime boundary."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            keys_to_delete: tuple[CandleKey, ...] = tuple(
                key
                for key, candle in self._candles.items()
                if (
                    candle.open_time < before
                    and (
                        normalized_symbol is None
                        or candle.symbol.upper() == normalized_symbol
                    )
                    and (interval is None or candle.interval is interval)
                )
            )

            for key in keys_to_delete:
                del self._candles[key]

        return len(keys_to_delete)

    async def count(
        self,
        *,
        symbol: str | None = None,
        interval: Interval | None = None,
    ) -> int:
        """Count stored candle records."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            return sum(
                1
                for candle in self._candles.values()
                if (
                    (
                        normalized_symbol is None
                        or candle.symbol.upper() == normalized_symbol
                    )
                    and (interval is None or candle.interval is interval)
                )
            )

    @staticmethod
    def _create_key(
        candle: Candle,
    ) -> CandleKey:
        """Create a unique in-memory candle key."""
        return (
            MemoryCandleRepository._normalize_symbol(candle.symbol),
            candle.interval,
            candle.open_time,
        )

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol
