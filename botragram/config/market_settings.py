"""
Botragram

Description:
    Market pair and trading timeframe settings model.

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
from dataclasses import dataclass

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.interval import Interval


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(slots=True)
class MarketSettings:
    """Settings defining market pair and candlestick intervals."""

    symbol: str = "BTCUSDT"
    base_asset: str = "BTC"
    quote_asset: str = "USDT"
    interval: Interval = Interval.M15
