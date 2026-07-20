"""
Trading Bot

Module:
    models.order

Description:
    Domain model representing an exchange order.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from models.enums import (
    ExchangeType,
    OrderSide,
    OrderStatus,
    OrderType,
)
from models.fee import Fee
from models.symbol import Symbol

__all__ = [
    "Order",
]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class Order:
    """Represents an exchange order."""

    exchange: ExchangeType
    symbol: Symbol

    order_id: str
    client_order_id: str | None

    side: OrderSide
    order_type: OrderType
    status: OrderStatus

    quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal

    price: Decimal | None
    average_price: Decimal | None

    cost: Decimal

    fee: Fee | None

    created_at: datetime
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate order."""

        # ------------------------------------------------------------------
        # Identifiers
        # ------------------------------------------------------------------

        if not self.order_id.strip():
            raise ValueError("order_id cannot be empty")

        if (
            self.client_order_id is not None
            and not self.client_order_id.strip()
        ):
            raise ValueError(
                "client_order_id cannot be empty"
            )

        # ------------------------------------------------------------------
        # Timestamp
        # ------------------------------------------------------------------

        if self.created_at.tzinfo is None:
            raise ValueError(
                "created_at must be timezone-aware"
            )

        if (
            self.updated_at is not None
            and self.updated_at.tzinfo is None
        ):
            raise ValueError(
                "updated_at must be timezone-aware"
            )

        # ------------------------------------------------------------------
        # Quantities
        # ------------------------------------------------------------------

        if self.quantity <= _ZERO:
            raise ValueError("quantity must be > 0")

        if self.filled_quantity < _ZERO:
            raise ValueError(
                "filled_quantity must be >= 0"
            )

        if self.remaining_quantity < _ZERO:
            raise ValueError(
                "remaining_quantity must be >= 0"
            )

        if (
            self.filled_quantity
            + self.remaining_quantity
            != self.quantity
        ):
            raise ValueError(
                "filled_quantity + remaining_quantity must equal quantity"
            )

        # ------------------------------------------------------------------
        # Prices
        # ------------------------------------------------------------------

        if (
            self.price is not None
            and self.price <= _ZERO
        ):
            raise ValueError("price must be > 0")

        if (
            self.average_price is not None
            and self.average_price <= _ZERO
        ):
            raise ValueError(
                "average_price must be > 0"
            )

        # ------------------------------------------------------------------
        # Cost
        # ------------------------------------------------------------------

        if self.cost < _ZERO:
            raise ValueError("cost must be >= 0")

    @property
    def is_open(self) -> bool:
        """Return True if the order is open."""

        return self.status is OrderStatus.OPEN

    @property
    def is_closed(self) -> bool:
        """Return True if the order is closed."""

        return self.status is OrderStatus.CLOSED

    @property
    def is_filled(self) -> bool:
        """Return True if the order is completely filled."""

        return self.remaining_quantity == _ZERO