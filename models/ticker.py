"""
Trading Bot

Module:
    models.ticker

Description:
    Domain model representing a market ticker.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.validators import (
    validate_decimal_non_negative,
    validate_decimal_positive,
    validate_greater_or_equal,
    validate_timezone_aware,
)
from models.symbol import Symbol

__all__ = [
    "Ticker",
]


@dataclass(slots=True, frozen=True)
class Ticker:
    """Represents the latest market ticker."""

    symbol: Symbol

    timestamp: datetime

    bid: Decimal
    ask: Decimal
    last: Decimal

    high: Decimal
    low: Decimal

    open: Decimal

    base_volume: Decimal
    quote_volume: Decimal

    def __post_init__(self) -> None:
        """Validate ticker."""

        validate_timezone_aware(
            self.timestamp,
            "timestamp",
        )

        validate_decimal_positive(
            self.bid,
            "bid",
        )

        validate_decimal_positive(
            self.ask,
            "ask",
        )

        validate_decimal_positive(
            self.last,
            "last",
        )

        validate_decimal_positive(
            self.high,
            "high",
        )

        validate_decimal_positive(
            self.low,
            "low",
        )

        validate_decimal_positive(
            self.open,
            "open",
        )

        validate_greater_or_equal(
            self.ask,
            self.bid,
            "ask",
        )

        validate_greater_or_equal(
            self.high,
            self.low,
            "high",
        )

        validate_decimal_non_negative(
            self.base_volume,
            "base_volume",
        )

        validate_decimal_non_negative(
            self.quote_volume,
            "quote_volume",
        )

    @property
    def spread(self) -> Decimal:
        """Return bid-ask spread."""

        return self.ask - self.bid

    @property
    def mid_price(self) -> Decimal:
        """Return midpoint price."""

        return (self.bid + self.ask) / Decimal("2")

    @property
    def change(self) -> Decimal:
        """Return absolute price change."""

        return self.last - self.open

    @property
    def change_percent(self) -> Decimal:
        """Return percentage price change."""

        return (
            (self.last - self.open)
            / self.open
            * Decimal("100")
        )