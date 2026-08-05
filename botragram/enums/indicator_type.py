"""
Botragram

Description:
    Supported technical indicator types.

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

__all__ = ["IndicatorType"]


# =============================================================================
# Enums
# =============================================================================
@unique
class IndicatorType(BaseEnum):
    """Supported technical indicator types."""

    # Trend
    EMA = "ema"
    SMA = "sma"
    WMA = "wma"
    HMA = "hma"

    # Momentum
    RSI = "rsi"
    MACD = "macd"
    STOCH = "stoch"
    CCI = "cci"

    # Volatility
    ATR = "atr"
    BBANDS = "bbands"

    # Trend Strength
    ADX = "adx"

    # Volume
    OBV = "obv"
    VWAP = "vwap"

    # Hybrid
    SUPERTREND = "supertrend"
    ICHIMOKU = "ichimoku"

    # Custom
    CUSTOM = "custom"
