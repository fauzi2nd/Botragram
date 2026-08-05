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
# Standard Library Imports
# =============================================================================
from enum import unique

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.base import BaseEnum

__all__ = ["OrderType"]


# =============================================================================
# Enums
# =============================================================================
@unique
class OrderType(BaseEnum):
    """Supported order types."""

    MARKET = "market"
    LIMIT = "limit"

    STOP = "stop"
    STOP_MARKET = "stop_market"

    TAKE_PROFIT = "take_profit"
    TAKE_PROFIT_MARKET = "take_profit_market"

    TRAILING_STOP = "trailing_stop"
