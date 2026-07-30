"""
Botragram

Description:
    Strategy default constants.

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
    "DEFAULT_CONFIRMATION_CANDLES",
    "DEFAULT_COOLDOWN_CANDLES",
    "DEFAULT_MIN_SIGNAL_STRENGTH",
    "DEFAULT_MAX_SIGNAL_AGE",
]

# =============================================================================
# Strategy
# =============================================================================

# Number of candles required to confirm a signal.
DEFAULT_CONFIRMATION_CANDLES: int = 1

# Number of candles to wait before opening another position.
DEFAULT_COOLDOWN_CANDLES: int = 0

# Minimum AI/strategy confidence required (0.0 - 1.0).
DEFAULT_MIN_SIGNAL_STRENGTH: Decimal = Decimal("0.70")

# Maximum age of a signal before it is discarded.
DEFAULT_MAX_SIGNAL_AGE: int = 3
