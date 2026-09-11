"""
Botragram

Description:
    Derivatives Open Interest market regimes.

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

__all__ = ["OpenInterestRegime"]


# =============================================================================
# Enums
# =============================================================================
@unique
class OpenInterestRegime(BaseEnum):
    """Derivatives Open Interest market regimes."""

    LONG_BUILDUP = "long_buildup"
    SHORT_COVERING = "short_covering"
    SHORT_BUILDUP = "short_buildup"
    LONG_LIQUIDATION = "long_liquidation"
    NEUTRAL = "neutral"
