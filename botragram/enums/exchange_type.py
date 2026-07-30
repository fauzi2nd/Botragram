"""
Botragram

Description:
    Supported cryptocurrency exchange types.

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

__all__ = ["ExchangeType"]


# =============================================================================
# Enums
# =============================================================================
@unique
class ExchangeType(BaseEnum):
    """Supported cryptocurrency exchange types."""

    BINANCE = "binance"
    BYBIT = "bybit"
    OKX = "okx"
    BITGET = "bitget"
