"""
Trading Bot

Module:
    models.symbol

Description:
    Domain model representing a tradable instrument.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from models.enums import ExchangeType, MarketType

__all__ = [
    "Symbol",
]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class Symbol:
    """Represents a tradable instrument and its trading rules."""

    exchange: ExchangeType
    market_type: MarketType

    symbol: str
    native_symbol: str

    base_asset: str
    quote_asset: str
    settle_asset: str | None

    price_precision: int
    quantity_precision: int

    tick_size: Decimal
    lot_size: Decimal

    min_quantity: Decimal
    max_quantity: Decimal | None

    min_notional: Decimal
    contract_size: Decimal

    active: bool = True

    def __post_init__(self) -> None:
        """Validate symbol metadata."""

        # ------------------------------------------------------------------
        # Required strings
        # ------------------------------------------------------------------

        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")

        if " " in self.symbol:
            raise ValueError("symbol must not contain spaces")

        if not self.native_symbol.strip():
            raise ValueError("native_symbol cannot be empty")

        if " " in self.native_symbol:
            raise ValueError("native_symbol must not contain spaces")

        if not self.base_asset.strip():
            raise ValueError("base_asset cannot be empty")

        if not self.quote_asset.strip():
            raise ValueError("quote_asset cannot be empty")

        if (
            self.settle_asset is not None
            and not self.settle_asset.strip()
        ):
            raise ValueError("settle_asset cannot be empty")

        # ------------------------------------------------------------------
        # Precision
        # ------------------------------------------------------------------

        if self.price_precision < 0:
            raise ValueError("price_precision must be >= 0")

        if self.quantity_precision < 0:
            raise ValueError("quantity_precision must be >= 0")

        # ------------------------------------------------------------------
        # Trading rules
        # ------------------------------------------------------------------

        if self.tick_size <= _ZERO:
            raise ValueError("tick_size must be > 0")

        if self.lot_size <= _ZERO:
            raise ValueError("lot_size must be > 0")

        if self.min_quantity <= _ZERO:
            raise ValueError("min_quantity must be > 0")

        if (
            self.max_quantity is not None
            and self.max_quantity <= _ZERO
        ):
            raise ValueError("max_quantity must be > 0")

        if (
            self.max_quantity is not None
            and self.max_quantity < self.min_quantity
        ):
            raise ValueError(
                "max_quantity must be >= min_quantity"
            )

        if self.min_notional < _ZERO:
            raise ValueError("min_notional must be >= 0")

        if self.contract_size <= _ZERO:
            raise ValueError("contract_size must be > 0")

    @property
    def is_spot(self) -> bool:
        """Return True if the instrument is traded on the spot market."""

        return self.market_type is MarketType.SPOT

    @property
    def is_derivative(self) -> bool:
        """Return True if the instrument is a derivative product."""

        return self.market_type in (
            MarketType.LINEAR,
            MarketType.INVERSE,
            MarketType.OPTION,
        )