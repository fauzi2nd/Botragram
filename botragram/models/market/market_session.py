"""
Botragram

Description:
    Market trading session model representing session status and schedule.

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
from datetime import datetime

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import AssetClass, MarketSessionStatus

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "MarketSession",
]


# =============================================================================
# Market Session Model
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class MarketSession:
    """Represent trading session status and schedule information for a symbol."""

    symbol: str
    asset_class: AssetClass
    status: MarketSessionStatus
    is_open: bool
    current_time: datetime
    next_open: datetime | None = None
    next_close: datetime | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Validate timezone awareness and symbol validity."""
        if not self.symbol.strip():
            raise ValueError("MarketSession requires a valid symbol")
        if self.current_time.tzinfo is None:
            raise ValueError("current_time must be timezone-aware")
        if self.next_open is not None and self.next_open.tzinfo is None:
            raise ValueError("next_open must be timezone-aware")
        if self.next_close is not None and self.next_close.tzinfo is None:
            raise ValueError("next_close must be timezone-aware")
