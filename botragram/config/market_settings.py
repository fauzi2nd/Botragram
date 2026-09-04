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
from botragram.constants import (
    DEFAULT_DISCOVERY_BATCH_SIZE,
    DEFAULT_DISCOVERY_CANDLE_DELAY_SECONDS,
    DEFAULT_DISCOVERY_MAX_SYMBOLS,
    DEFAULT_DISCOVERY_TOP_N,
    DEFAULT_DISCOVERY_UNIVERSE_LIMIT,
)
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
    discovery_universe_limit: int = DEFAULT_DISCOVERY_UNIVERSE_LIMIT
    discovery_batch_size: int = DEFAULT_DISCOVERY_BATCH_SIZE
    discovery_top_n: int = DEFAULT_DISCOVERY_TOP_N
    discovery_cadence_seconds: int | None = None
    discovery_candle_delay_seconds: float = DEFAULT_DISCOVERY_CANDLE_DELAY_SECONDS

    def __post_init__(self) -> None:
        """Validate bounded market-discovery configuration."""
        if (
            isinstance(self.discovery_max_symbols, bool)
            or self.discovery_max_symbols <= 0
        ):
            raise ValueError("Discovery maximum symbols must be a positive integer")
        if (
            isinstance(self.discovery_universe_limit, bool)
            or self.discovery_universe_limit <= 0
        ):
            raise ValueError("Discovery universe limit must be a positive integer")
        if (
            isinstance(self.discovery_batch_size, bool)
            or self.discovery_batch_size <= 0
        ):
            raise ValueError("Discovery batch size must be a positive integer")
        if isinstance(self.discovery_top_n, bool) or self.discovery_top_n <= 0:
            raise ValueError("Discovery top N must be a positive integer")
        if self.discovery_batch_size > self.discovery_universe_limit:
            raise ValueError("Discovery batch size must not exceed universe limit")
        if self.discovery_cadence_seconds is not None and (
            isinstance(self.discovery_cadence_seconds, bool)
            or self.discovery_cadence_seconds <= 0
        ):
            raise ValueError("Discovery cadence must be a positive integer")
        if (
            isinstance(self.discovery_candle_delay_seconds, bool)
            or self.discovery_candle_delay_seconds < 0.0
        ):
            raise ValueError(
                "Discovery candle delay seconds must be a non-negative number"
            )

    @property
    def symbol(self) -> str:
        """Combined market symbol."""
        return f"{self.base_asset}{self.quote_asset}"
