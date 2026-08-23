"""
Botragram

Description:
    Immutable market-universe entry model.

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
from decimal import Decimal

__all__ = [
    "MarketUniverseEntry",
]


# =============================================================================
# Constants
# =============================================================================
_ZERO = Decimal("0")


# =============================================================================
# Model Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class MarketUniverseEntry:
    """Represent one normalized symbol and its 24-hour quote volume."""

    symbol: str
    quote_volume: Decimal

    def __post_init__(self) -> None:
        """Normalize the symbol and reject unusable quote-volume facts."""
        normalized_symbol = self.symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Market-universe symbol must not be empty")

        if not self.quote_volume.is_finite():
            raise ValueError("Market-universe quote volume must be finite")

        if self.quote_volume < _ZERO:
            raise ValueError("Market-universe quote volume must not be negative")

        object.__setattr__(self, "symbol", normalized_symbol)
