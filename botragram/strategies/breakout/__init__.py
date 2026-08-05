"""
Botragram

Description:
    Breakout strategies package initialization.

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
from botragram.strategies.breakout.bollinger_breakout import (
    BollingerBreakoutStrategy,
)

__all__ = [
    "BollingerBreakoutStrategy",
]
