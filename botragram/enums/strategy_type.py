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
from botragram.enums.base import BaseEnum

__all__ = ["StrategyType"]


# =============================================================================
# Enums
# =============================================================================
@unique
class StrategyType(BaseEnum):
    """Supported trading strategy types."""

    BOLLINGER_BREAKOUT = "bollinger_breakout"
    EMA_CROSS = "ema_cross"
    EMA_RSI = "ema_rsi"
    EMA_SCALPING = "ema_scalping"
    MACD_SWING = "macd_swing"
    SUPERTREND = "supertrend"
    CUSTOM = "custom"
