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

    ADX_TREND = "adx_trend"
    BOLLINGER_BREAKOUT = "bollinger_breakout"
    CHOCH_FVG = "choch_fvg"
    EMA_CROSS = "ema_cross"
    EMA_RSI = "ema_rsi"
    EMA_SCALPING = "ema_scalping"
    HIGH_CONFLUENCE_EXHAUSTION = "high_confluence_exhaustion"
    ICHIMOKU_CLOUD = "ichimoku_cloud"
    MACD_SWING = "macd_swing"
    RSI_BB_SCALPING = "rsi_bb_scalping"
    SUPERTREND = "supertrend"
    VWAP_BREAKOUT = "vwap_breakout"
    CUSTOM = "custom"
