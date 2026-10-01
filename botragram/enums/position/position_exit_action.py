"""
Botragram

Description:
    Position exit action enumeration.

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

__all__ = ["PositionExitAction"]


# =============================================================================
# Enums
# =============================================================================
@unique
class PositionExitAction(BaseEnum):
    """Supported position exit actions."""

    HOLD = "hold"
    EARLY_CUT_LOSS = "early_cut_loss"
    EARLY_TAKE_PROFIT = "early_take_profit"
