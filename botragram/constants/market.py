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
    "DEFAULT_MAKER_FEE_RATE",
    "DEFAULT_TAKER_FEE_RATE",
    "DEFAULT_SLIPPAGE_RATE",
]

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
