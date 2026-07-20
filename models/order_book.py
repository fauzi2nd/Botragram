"""
Trading Bot

Module:
    models.order_book

Description:
    Domain model representing an order book snapshot.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from models.order_book_level import OrderBookLevel
from models.symbol import Symbol

__all__ = [
    "OrderBook",
]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class OrderBook:
    """Represents an order book snapshot."""

    symbol: Symbol
    timestamp: datetime

    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]

    def __post_init__(self) -> None:
        """Validate order book."""

        if self.timestamp.tzinfo is None:
            raise ValueError(
                "timestamp must be timezone-aware"
            )

        for previous, current in zip(
            self.bids,
            self.bids[1:],
        ):
            if previous.price < current.price:
                raise ValueError(
                    "bids must be sorted in descending price order"
                )

        for previous, current in zip(
            self.asks,
            self.asks[1:],
        ):
            if previous.price > current.price:
                raise ValueError(
                    "asks must be sorted in ascending price order"
                )

    @property
    def best_bid(self) -> OrderBookLevel | None:
        """Return the best bid level."""

        if not self.bids:
            return None

        return self.bids[0]

    @property
    def best_ask(self) -> OrderBookLevel | None:
        """Return the best ask level."""

        if not self.asks:
            return None

        return self.asks[0]

    @property
    def spread(self) -> Decimal | None:
        """Return the bid-ask spread."""

        if (
            self.best_bid is None
            or self.best_ask is None
        ):
            return None

        return (
            self.best_ask.price
            - self.best_bid.price
        )