"""
Botragram

Description:
    Default technical indicator configurations.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

__all__ = [
    # EMA
    "DEFAULT_EMA_FAST_PERIOD",
    "DEFAULT_EMA_SLOW_PERIOD",
    # SMA
    "DEFAULT_SMA_PERIOD",
    # RSI
    "DEFAULT_RSI_PERIOD",
    "DEFAULT_RSI_OVERBOUGHT",
    "DEFAULT_RSI_OVERSOLD",
    # MACD
    "DEFAULT_MACD_FAST_PERIOD",
    "DEFAULT_MACD_SLOW_PERIOD",
    "DEFAULT_MACD_SIGNAL_PERIOD",
    # ATR
    "DEFAULT_ATR_PERIOD",
    # Bollinger Bands
    "DEFAULT_BBANDS_PERIOD",
    "DEFAULT_BBANDS_STDDEV",
    # ADX
    "DEFAULT_ADX_PERIOD",
]

# =============================================================================
# EMA
# =============================================================================
DEFAULT_EMA_FAST_PERIOD: int = 9
DEFAULT_EMA_SLOW_PERIOD: int = 21

# =============================================================================
# SMA
# =============================================================================
DEFAULT_SMA_PERIOD: int = 20

# =============================================================================
# RSI
# =============================================================================
DEFAULT_RSI_PERIOD: int = 14
DEFAULT_RSI_OVERBOUGHT: float = 70.0
DEFAULT_RSI_OVERSOLD: float = 30.0

# =============================================================================
# MACD
# =============================================================================
DEFAULT_MACD_FAST_PERIOD: int = 12
DEFAULT_MACD_SLOW_PERIOD: int = 26
DEFAULT_MACD_SIGNAL_PERIOD: int = 9

# =============================================================================
# ATR
# =============================================================================
DEFAULT_ATR_PERIOD: int = 14

# =============================================================================
# Bollinger Bands
# =============================================================================
DEFAULT_BBANDS_PERIOD: int = 20
DEFAULT_BBANDS_STDDEV: float = 2.0

# =============================================================================
# ADX
# =============================================================================
DEFAULT_ADX_PERIOD: int = 14
