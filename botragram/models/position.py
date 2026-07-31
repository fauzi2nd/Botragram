"""
Botragram

Description:
    Trading position model.

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
from botragram.enums import PositionSide

__all__ = [
    "Position",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class Position:
    """Immutable trading position."""

    symbol: str
    side: PositionSide

    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal

    unrealized_pnl: Decimal
    leverage: int

    opened_at: datetime
    updated_at: datetime
