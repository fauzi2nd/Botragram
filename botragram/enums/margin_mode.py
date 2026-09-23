"""
Botragram

Description:
    Margin mode enumeration for futures trading positions and orders.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.base import StrEnum

__all__ = [
    "MarginMode",
]


# =============================================================================
# Enums
# =============================================================================
class MarginMode(StrEnum):
    """Margin mode for futures trading positions and orders."""

    CROSSED = "crossed"
    ISOLATED = "isolated"
