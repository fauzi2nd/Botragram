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
from botragram.strategies.trend.adx_trend import ADXTrendStrategy
from botragram.strategies.trend.ema_cross import EMACrossStrategy
from botragram.strategies.trend.ema_rsi import EMARsiStrategy
from botragram.strategies.trend.ichimoku_cloud import IchimokuCloudStrategy
from botragram.strategies.trend.supertrend import SupertrendStrategy

__all__ = [
    "ADXTrendStrategy",
    "EMACrossStrategy",
    "EMARsiStrategy",
    "IchimokuCloudStrategy",
    "SupertrendStrategy",
]
