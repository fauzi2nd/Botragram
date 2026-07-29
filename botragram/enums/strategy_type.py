"""
Botragram

Description:
    Strategy type enumeration.

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
class StrategyType(str, Enum):
    """Trading strategy type."""

    EMA_CROSS = "EMA_CROSS"
    EMA_RSI = "EMA_RSI"
    SUPERTREND = "SUPERTREND"
