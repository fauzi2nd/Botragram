"""
Botragram

Description:
    Data models for candlestick backfill and synchronization.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from dataclasses import dataclass
from datetime import datetime

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, MarketType

__all__ = [
    "BackfillRequest",
    "BackfillResult",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class BackfillRequest:
    """Immutable request specification for candlestick backfill and sync."""

    symbols: tuple[str, ...] = ()
    universe_size: int | None = None
    interval: Interval = Interval.M1
    market_type: MarketType = MarketType.FUTURES
    start_time: datetime | None = None
    end_time: datetime | None = None
    watch: bool = False
    watch_interval_seconds: int = 300
    database_path: str | None = None
    concurrency: int = 3

    def __post_init__(self) -> None:
        """Validate backfill request boundaries."""
        if not self.symbols and (self.universe_size is None or self.universe_size <= 0):
            raise ValueError(
                "Backfill request requires either explicit symbols or universe_size > 0"
            )

        if self.watch_interval_seconds <= 0:
            raise ValueError("Watch interval must be greater than zero seconds")

        if self.concurrency <= 0:
            raise ValueError("Concurrency must be greater than zero")

        normalized_symbols = tuple(s.strip().upper() for s in self.symbols if s.strip())
        object.__setattr__(self, "symbols", normalized_symbols)


@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class BackfillResult:
    """Summary result of a completed backfill execution."""

    symbol_counts: dict[str, int]
    total_candles: int
    duration_seconds: float
    venue_name: str = "Bybit Mainnet"
