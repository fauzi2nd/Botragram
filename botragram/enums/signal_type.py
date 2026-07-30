"""
Botragram

Description:
    Strategy signal type enumeration.

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
from enums.base import BaseEnum

__all__ = ["SignalType"]


# =============================================================================
# Enums
# =============================================================================
@unique
class SignalType(BaseEnum):
    """Supported strategy signal types."""

    BUY = "buy"
    SELL = "sell"

    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"

    HOLD = "hold"
