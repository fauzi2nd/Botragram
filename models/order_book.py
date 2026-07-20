"""
Trading Bot

Module:
    models.order_book

Description:
    Domain model representing a market order book.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.validators import (
    validate_collection_not_empty,
    validate_greater_or_equal,
    validate_timezone_aware,
)
from models.order_book_level import OrderBookLevel
from models.symbol import Symbol

__all__ = [
    "OrderBook",
]


@dataclass(slots=True, frozen=True)
class OrderBook:
    """Represents a market order book."""

    symbol: Symbol

    timestamp: datetime

    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]

    def __post_init__(self) -> None:
        """Validate order book."""

        validate_timezone_aware(
            self.timestamp,
            "timestamp",
        )

        validate_collection_not_empty(
            self.bids,
            "bids",
        )

        validate_collection_not_empty(
            self.asks,
            "asks",
        )

        # ------------------------------------------------------------------
        # Bid levels (highest -> lowest)
        # ------------------------------------------------------------------

        for previous, current in zip(
            self.bids,
            self.bids[1:],
        ):
            validate_greater_or_equal(
                previous.price,
                current.price,
                "bids",
            )

        # ------------------------------------------------------------------
        # Ask levels (lowest -> highest)
        # ------------------------------------------------------------------

        for previous, current in zip(
            self.asks,
            self.asks[1:],
        ):
            validate_greater_or_equal(
                current.price,
                previous.price,
                "asks",
            )

        # ------------------------------------------------------------------
        # Best prices
        # ------------------------------------------------------------------

        validate_greater_or_equal(
            self.best_ask.price,
            self.best_bid.price,
            "best_ask.price",
        )

   