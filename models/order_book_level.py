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

__all__ = [
    "OrderBookLevel",
]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class OrderBookLevel:
    """Represents a single order book level."""

    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        """Validate order book level."""

        if self.price <= _ZERO:
            raise ValueError("price must be > 0")

        if self.quantity <= _ZERO:
            raise ValueError("quantity must be > 0")