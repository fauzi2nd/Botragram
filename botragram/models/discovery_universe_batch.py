"""
Botragram

Description:
    Immutable ranked discovery-universe batch model.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models.market_universe_entry import MarketUniverseEntry

__all__ = [
    "DiscoveryUniverseBatch",
]


# =============================================================================
# Model Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class DiscoveryUniverseBatch:
    """Represent one immutable contiguous window of a ranked universe."""

    entries: tuple[MarketUniverseEntry, ...]
    universe_size: int
    rank_start: int
    rank_end: int

    def __post_init__(self) -> None:
        """Reject empty or internally inconsistent ranked windows."""
        if not self.entries:
            raise ValueError("Discovery universe batch entries must not be empty")
        if isinstance(self.universe_size, bool) or self.universe_size <= 0:
            raise ValueError("Discovery universe size must be a positive integer")
        if isinstance(self.rank_start, bool) or self.rank_start <= 0:
            raise ValueError("Discovery universe start rank must be positive")
        if isinstance(self.rank_end, bool) or self.rank_end <= 0:
            raise ValueError("Discovery universe end rank must be positive")
        if self.rank_start > self.rank_end:
            raise ValueError("Discovery universe rank range must be ordered")
        if self.rank_end > self.universe_size:
            raise ValueError("Discovery universe rank range exceeds its snapshot")
        expected_size = self.rank_end - self.rank_start + 1
        if len(self.entries) != expected_size:
            raise ValueError("Discovery universe batch size does not match its ranks")
