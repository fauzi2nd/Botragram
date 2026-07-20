"""
Trading Bot

Module:
    models.order_book_level

Description:
    Domain model representing a single order book level.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.validators import (
    validate_decimal_positive,
)

__all__ = [
    "OrderBookLevel",
]


@dataclass(slots=True, frozen=True)
class OrderBookLevel:
    """Represents a single order book level."""

    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        """Validate order book level."""

        validate_decimal_positive(
            self.price,
            "price",
        )

        validate_decimal_positive(
            self.quantity,
            "quantity",
        )

    @property
    def notional(self) -> Decimal:
        """Return price × quantity."""

        return self.price * self.quantity