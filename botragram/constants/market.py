"""
Botragram

Description:
    Market default constants.

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
from decimal import Decimal

__all__ = [
    "DEFAULT_DISCOVERY_BATCH_SIZE",
    "DEFAULT_DISCOVERY_MAX_SYMBOLS",
    "DEFAULT_DISCOVERY_TOP_N",
    "DEFAULT_DISCOVERY_UNIVERSE_LIMIT",
    "DEFAULT_MAKER_FEE_RATE",
    "DEFAULT_TAKER_FEE_RATE",
    "DEFAULT_SLIPPAGE_RATE",
]

# =============================================================================
# Market Discovery
# =============================================================================
DEFAULT_DISCOVERY_UNIVERSE_LIMIT: int = 100
DEFAULT_DISCOVERY_BATCH_SIZE: int = 20
DEFAULT_DISCOVERY_MAX_SYMBOLS: int = 20
DEFAULT_DISCOVERY_TOP_N: int = 5

# =============================================================================
# Trading Fees (fallback values)
# =============================================================================
# Used only when exchange fee information is unavailable.
DEFAULT_MAKER_FEE_RATE: Decimal = Decimal("0.0002")
DEFAULT_TAKER_FEE_RATE: Decimal = Decimal("0.0005")

# =============================================================================
# Trading
# =============================================================================
# Default assumed slippage (0.05%)
DEFAULT_SLIPPAGE_RATE: Decimal = Decimal("0.0005")
