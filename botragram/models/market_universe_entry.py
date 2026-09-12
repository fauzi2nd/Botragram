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
_TWO = Decimal("2")
_BASIS_POINTS = Decimal("10000")


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
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    spread_bps: Decimal | None = None

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

        if self.bid_price is not None:
            if not self.bid_price.is_finite() or self.bid_price <= _ZERO:
                raise ValueError(
                    "Market-universe bid price must be positive and finite"
                )

        if self.ask_price is not None:
            if not self.ask_price.is_finite() or self.ask_price <= _ZERO:
                raise ValueError(
                    "Market-universe ask price must be positive and finite"
                )

        if self.bid_price is not None and self.ask_price is not None:
            if self.ask_price < self.bid_price:
                raise ValueError(
                    "Market-universe ask price cannot be less than bid price"
                )

        spread_bps = self.spread_bps
        if spread_bps is not None:
            if not spread_bps.is_finite() or spread_bps < _ZERO:
                raise ValueError(
                    "Market-universe spread_bps must be finite and non-negative"
                )
        elif self.bid_price is not None and self.ask_price is not None:
            midpoint = (self.bid_price + self.ask_price) / _TWO
            if midpoint > _ZERO:
                calculated = (
                    (self.ask_price - self.bid_price) / midpoint * _BASIS_POINTS
                )
                object.__setattr__(self, "spread_bps", calculated)
