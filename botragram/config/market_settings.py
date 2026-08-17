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
from botragram.constants import DEFAULT_DISCOVERY_MAX_SYMBOLS, DEFAULT_DISCOVERY_TOP_N
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
    discovery_max_symbols: int = DEFAULT_DISCOVERY_MAX_SYMBOLS
    discovery_top_n: int = DEFAULT_DISCOVERY_TOP_N

    def __post_init__(self) -> None:
        """Validate bounded market-discovery configuration."""
        if self.discovery_max_symbols <= 0:
            raise ValueError("Discovery maximum symbols must be greater than zero")

        if self.discovery_top_n <= 0:
            raise ValueError("Discovery top N must be greater than zero")

    @property
    def symbol(self) -> str:
        """Combined market symbol."""
        return f"{self.base_asset}{self.quote_asset}"
