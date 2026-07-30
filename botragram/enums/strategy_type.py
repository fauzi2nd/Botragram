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
# Standard Library Imports
# =============================================================================
from enum import unique

# =============================================================================
# Local Imports
# =============================================================================
from enums.base import BaseEnum

__all__ = ["StrategyType"]


# =============================================================================
# Enums
# =============================================================================
@unique
class StrategyType(BaseEnum):
    """Supported trading strategy types."""

    EMA_CROSS = "ema_cross"
    EMA_RSI = "ema_rsi"
    SUPERTREND = "supertrend"

    CUSTOM = "custom"
