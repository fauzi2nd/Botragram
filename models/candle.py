"""
Trading Bot

Module:
    models.candle

Description:
    Domain model representing a single OHLCV candle.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from models.enums import Timeframe
from models.symbol import Symbol

__all__ = [
    "Candle",
]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class Candle:
    """Represents a single OHLCV candle."""

    symbol: Symbol
    timeframe: Timeframe

    open_time: datetime

    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal

    volume: Decimal

    def __post_init__(self) -> None:
        """Validate candle data."""

        # ------------------------------------------------------------------
        # Timestamp
        # ------------------------------------------------------------------

        if self.open_time.tzinfo is None:
            raise ValueError("open_time must be timezone-aware")

        # ------------------------------------------------------------------
        # Price validation
        # ------------------------------------------------------------------

        if self.high_price < self.low_price:
            raise ValueError("high_price must be >= low_price")

        if self.high_price < self.open_price:
            raise ValueError("high_price must be >= open_price")

        if self.high_price < self.close_price:
            raise ValueError("high_price must be >= close_price")

        if self.low_price > self.open_price:
            raise ValueError("low_price must be <= open_price")

        if self.low_price > self.close_price:
            raise ValueError("low_price must be <= close_price")

        # ------------------------------------------------------------------
        # Volume
        # ------------------------------------------------------------------

        if self.volume < _ZERO:
            raise ValueError("volume must be >= 0")

    @property
    def bullish(self) -> bool:
        """Return True if the candle is bullish."""

        return self.close_price > self.open_price

    @property
    def bearish(self) -> bool:
        """Return True if the candle is bearish."""

        return self.close_price < self.open_price

    @property
    def body_size(self) -> Decimal:
        """Return candle body size."""

        return abs(self.close_price - self.open_price)

    @property
    def range_size(self) -> Decimal:
        """Return candle total range."""

        return self.high_price - self.low_price