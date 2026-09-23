"""
Botragram

Description:
    Immutable discovery scan report model for market-wide discovery.

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
from botragram.models.signal import Signal

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "DiscoveryScanReport",
]


# =============================================================================
# Model Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class DiscoveryScanReport:
    """Represent one completed market-wide opportunity discovery scan."""

    universe_size: int
    scanned_count: int
    signals: tuple[Signal, ...] = ()

    def __post_init__(self) -> None:
        """Validate non-negative bounds and internal consistency."""
        if isinstance(self.universe_size, bool) or self.universe_size < 0:
            raise ValueError("Discovery universe size must be a non-negative integer")
        if isinstance(self.scanned_count, bool) or self.scanned_count < 0:
            raise ValueError("Discovery scanned count must be a non-negative integer")
        if self.scanned_count > self.universe_size:
            raise ValueError("Discovery scanned count cannot exceed universe size")
