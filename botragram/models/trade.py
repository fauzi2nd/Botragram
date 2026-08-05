"""
Botragram

Description:
    Executed trade model.

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
from botragram.enums import OrderSide

__all__ = [
    "Trade",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class Trade:
    """Immutable executed trade (exchange fill)."""

    trade_id: str
    order_id: str

    symbol: str

    side: OrderSide

    price: Decimal
    quantity: Decimal
    quote_quantity: Decimal

    fee: Decimal
    fee_asset: str

    executed_at: datetime

    # Futures exchanges may provide this value.
    # Spot exchanges will typically return None.
    realized_pnl: Decimal | None = None
