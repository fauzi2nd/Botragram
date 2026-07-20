"""
Trading Bot

Module:
    models.order_request

Description:
    Domain model representing a request to create an order.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from models.enums import OrderSide, OrderType
from models.symbol import Symbol

__all__ = [
    "OrderRequest",
]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class OrderRequest:
    """Represents a request to create an order."""

    symbol: Symbol

    side: OrderSide
    order_type: OrderType

    quantity: Decimal
    price: Decimal | None = None

    def __post_init__(self) -> None:
        """Validate order request."""

        if self.quantity <= _ZERO:
            raise ValueError("quantity must be > 0")

        if (
            self.price is not None
            and self.price <= _ZERO
        ):
            raise ValueError("price must be > 0")

        if (
            self.order_type is OrderType.LIMIT
            and self.price is None
        ):
            raise ValueError(
                "LIMIT orders require a price"
            )

        if (
            self.order_type is OrderType.MARKET
            and self.price is not None
        ):
            raise ValueError(
                "MARKET orders must not specify a price"
            )