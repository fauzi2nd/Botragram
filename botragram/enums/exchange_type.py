"""
Botragram

Description:
    Supported crypto exchange types.

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
class ExchangeType(str, Enum):
    """Supported cryptocurrency exchange types."""

    BINANCE = "binance"
    BYBIT = "bybit"
    OKX = "okx"
    BITGET = "bitget"
