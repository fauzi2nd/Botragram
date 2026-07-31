"""
Botragram

Description:
    Market ticker model.

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

__all__ = [
    "Ticker",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class Ticker:
    """Immutable market ticker."""

    symbol: str

    bid_price: Decimal
    ask_price: Decimal
    last_price: Decimal

    timestamp: datetime
