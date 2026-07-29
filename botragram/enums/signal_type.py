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
# Standard Library
# =============================================================================
from enum import Enum, unique


# =============================================================================
# Enums
# =============================================================================
@unique
class SignalType(str, Enum):
    """Trading strategy signal type."""

    BUY_ENTRY = "BUY_ENTRY"
    SELL_ENTRY = "SELL_ENTRY"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    NEUTRAL = "NEUTRAL"
