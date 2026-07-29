"""
Botragram

Description:
    Indicators package initialization.

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
from botragram.indicators.atr import calculate_atr
from botragram.indicators.ema import calculate_ema
from botragram.indicators.macd import MACDResult, calculate_macd
from botragram.indicators.rsi import calculate_rsi
from botragram.indicators.sma import calculate_sma
from botragram.indicators.supertrend import (
    SupertrendResult,
    calculate_supertrend,
)

__all__ = [
    "MACDResult",
    "SupertrendResult",
    "calculate_atr",
    "calculate_ema",
    "calculate_macd",
    "calculate_rsi",
    "calculate_sma",
    "calculate_supertrend",
]
