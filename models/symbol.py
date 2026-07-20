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

from core.validators import (
    validate_decimal_non_negative,
    validate_decimal_positive,
    validate_greater_or_equal,
    validate_int_non_negative,
    validate_no_whitespace,
    validate_not_empty,
)
from models.enums import ExchangeType, MarketType

__all__ = [
    "Symbol",
]


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
        # Strings
        # ------------------------------------------------------------------

        validate_not_empty(self.symbol, "symbol")
        validate_no_whitespace(self.symbol, "symbol")

        validate_not_empty(
            self.native_symbol,
            "native_symbol",
        )
        validate_no_whitespace(
            self.native_symbol,
            "native_symbol",
        )

        validate_not_empty(
            self.base_asset,
            "base_asset",
        )

        validate_not_empty(
            self.quote_asset,
            "quote_asset",
        )

        if self.settle_asset is not None:
            validate_not_empty(
                self.settle_asset,
                "settle_asset",
            )

        # ------------------------------------------------------------------
        # Precision
        # ------------------------------------------------------------------

        validate_int_non_negative(
            self.price_precision,
            "price_precision",
        )

        validate_int_non_negative(
            self.quantity_precision,
            "quantity_precision",
        )

        # ------------------------------------------------------------------
        # Trading Rules
        # ------------------------------------------------------------------

        validate_decimal_positive(
            self.tick_size,
            "tick_size",
        )

        validate_decimal_positive(
            self.lot_size,
            "lot_size",
        )

        validate_decimal_positive(
            self.min_quantity,
            "min_quantity",
        )

        if self.max_quantity is not None:
            validate_decimal_positive(
                self.max_quantity,
                "max_quantity",
            )

            validate_greater_or_equal(
                self.max_quantity,
                self.min_quantity,
                "max_quantity",
            )

        validate_decimal_non_negative(
            self.min_notional,
            "min_notional",
        )

        validate_decimal_positive(
            self.contract_size,
            "contract_size",
        )

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