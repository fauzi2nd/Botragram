"""
Botragram

Description:
    Market session status enumeration for trading calendar states.

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
from enum import StrEnum

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "MarketSessionStatus",
]


# =============================================================================
# Market Session Status Enum
# =============================================================================
class MarketSessionStatus(StrEnum):
    """Trading session state indicating current market availability."""

    OPEN = "open"
    CLOSED = "closed"
    BREAK = "break"
    WEEKEND = "weekend"
