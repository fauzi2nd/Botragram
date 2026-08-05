"""
Botragram

Description:
    Volatility indicators package initialization.

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
from botragram.indicators.volatility.atr import calculate_atr
from botragram.indicators.volatility.bollinger_bands import (
    BollingerBandsResult,
    calculate_bollinger_bands,
)

__all__ = [
    "BollingerBandsResult",
    "calculate_atr",
    "calculate_bollinger_bands",
]
