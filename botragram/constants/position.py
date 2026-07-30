"""
Botragram

Description:
    Position default constants.

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
    "DEFAULT_LEVERAGE",
    "DEFAULT_STOP_LOSS_RATE",
    "DEFAULT_TAKE_PROFIT_RATE",
    "DEFAULT_TRAILING_STOP_RATE",
]

# =============================================================================
# Position
# =============================================================================

# Default leverage used when no strategy- or user-specific value is provided.
DEFAULT_LEVERAGE: Decimal = Decimal("1")

# Default stop-loss distance from the entry price (2%).
DEFAULT_STOP_LOSS_RATE: Decimal = Decimal("0.02")

# Default take-profit distance from the entry price (4%).
DEFAULT_TAKE_PROFIT_RATE: Decimal = Decimal("0.04")

# Default trailing-stop distance from the reference price (1%).
DEFAULT_TRAILING_STOP_RATE: Decimal = Decimal("0.01")
