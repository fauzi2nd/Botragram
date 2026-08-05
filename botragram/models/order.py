"""
Botragram

Description:
    Trading order model.

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
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OrderSide, OrderStatus, OrderType

__all__ = [
    "Order",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class Order:
    """Immutable trading order."""

    order_id: str
    symbol: str

    side: OrderSide
    order_type: OrderType
    status: OrderStatus

    quantity: Decimal
    executed_quantity: Decimal

    created_at: datetime
    updated_at: datetime

    price: Decimal | None = None
    stop_price: Decimal | None = None
