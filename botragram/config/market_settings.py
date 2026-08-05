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
from botragram.enums import Interval

__all__ = [
    "MarketSettings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class MarketSettings:
    """Settings defining market pair and candlestick interval."""

    base_asset: str = "BTC"
    quote_asset: str = "USDT"
    interval: Interval = Interval.M15

    @property
    def symbol(self) -> str:
        """Combined market symbol."""
        return f"{self.base_asset}{self.quote_asset}"
