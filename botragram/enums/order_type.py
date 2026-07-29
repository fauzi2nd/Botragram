"""
Botragram

Description:
    Order type enumeration.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from enum import Enum, unique


# =============================================================================
# Enums
# =============================================================================
@unique
class OrderType(str, Enum):
    """Trading order type."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
