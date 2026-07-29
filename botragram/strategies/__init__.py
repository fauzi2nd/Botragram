"""
Botragram

Description:
    Strategies package initialization.

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
from botragram.strategies.base_strategy import BaseStrategy
from botragram.strategies.ema_cross import EMACrossStrategy
from botragram.strategies.ema_rsi import EMARSIStrategy
from botragram.strategies.supertrend import SupertrendStrategy

__all__ = [
    "BaseStrategy",
    "EMACrossStrategy",
    "EMARSIStrategy",
    "SupertrendStrategy",
]
