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

from core.validators import (
    validate_decimal_non_negative,
    validate_greater_or_equal,
    validate_less_or_equal,
    validate_timezone_aware,
)
from models.enums import Timeframe
from models.symbol import Symbol

__all__ = [
    "Candle",
]


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

        validate_timezone_aware(
            self.open_time,
            "open_time",
        )

        # ------------------------------------------------------------------
        # Price
        # ------------------------------------------------------------------

        validate_greater_or_equal(
            self.high_price,
            self.low_price,
            "high_price",
        )

        validate_greater_or_equal(
            self.high_price,
            self.open_price,
            "high_price",
        )

        validate_greater_or_equal(
            self.high_price,
            self.close_price,
            "high_price",
        )

        validate_less_or_equal(
            self.low_price,
            self.open_price,
            "low_price",
        )

        validate_less_or_equal(
            self.low_price,
            self.close_price,
            "low_price",
        )

        # ------------------------------------------------------------------
        # Volume
        # ------------------------------------------------------------------

        validate_decimal_non_negative(
            self.volume,
            "volume",
        )

    @property
    def bullish(self) -> bool:
        """Return True if the candle closed above its open."""

        return self.close_price > self.open_price

    @property
    def bearish(self) -> bool:
        """Return True if the candle closed below its open."""

        return self.close_price < self.open_price

    @property
    def neutral(self) -> bool:
        """Return True if the candle closed at its open."""

        return self.close_price == self.open_price

    @property
    def body_size(self) -> Decimal:
        """Return the candle body size."""

        return abs(self.close_price - self.open_price)

    @property
    def upper_shadow(self) -> Decimal:
        """Return the upper shadow size."""

        return self.high_price - max(
            self.open_price,
            self.close_price,
        )

    @property
    def lower_shadow(self) -> Decimal:
        """Return the lower shadow size."""

        return min(
            self.open_price,
            self.close_price,
        ) - self.low_price

    @property
    def range_size(self) -> Decimal:
        """Return the total candle range."""

        return self.high_price - self.low_price

    @property
    def is_doji(self) -> bool:
        """Return True if the candle has no body."""

        return self.open_price == self.close_price