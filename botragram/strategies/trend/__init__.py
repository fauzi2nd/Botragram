"""
Botragram

Description:
    Trend strategies package initialization.

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
from botragram.strategies.trend.ema_cross import EMACrossStrategy
from botragram.strategies.trend.ema_rsi import EMARsiStrategy
from botragram.strategies.trend.supertrend import SupertrendStrategy

__all__ = [
    "EMACrossStrategy",
    "EMARsiStrategy",
    "SupertrendStrategy",
]
