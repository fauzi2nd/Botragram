"""
Trading Bot

Module:
    models.trade

Description:
    Domain model representing a single trade execution.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from models.enums import ExchangeType, OrderSide
from models.fee import Fee
from models.symbol import Symbol

__all__ = [
    "Trade",
]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class Trade:
    """Represents a single trade execution."""

    exchange: ExchangeType
    symbol: Symbol

    trade_id: str
    order_id: str

    side: OrderSide

    quantity: Decimal
    price: Decimal
    cost: Decimal

    fee: Fee | None

    timestamp: datetime

    def __post_init__(self) -> None:
        """Validate trade."""

        # ------------------------------------------------------------------
        # Identifiers
        # ------------------------------------------------------------------

        if not self.trade_id.strip():
            raise ValueError("trade_id cannot be empty")

        if not self.order_id.strip():
            raise ValueError("order_id cannot be empty")

        # ------------------------------------------------------------------
        # Timestamp
        # ------------------------------------------------------------------

        if self.timestamp.tzinfo is None:
            raise ValueError(
                "timestamp must be timezone-aware"
            )

        # ------------------------------------------------------------------
        # Execution
        # ------------------------------------------------------------------

        if self.quantity <= _ZERO:
            raise ValueError("quantity must be > 0")

        if self.price <= _ZERO:
            raise ValueError("price must be > 0")

        if self.cost < _ZERO:
            raise ValueError("cost must be >= 0")