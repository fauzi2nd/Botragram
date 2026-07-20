"""
Trading Bot

Module:
    models.ticker

Description:
    Domain model representing a market ticker snapshot.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from models.symbol import Symbol

__all__ = [
    "Ticker",
]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class Ticker:
    """Represents a market ticker snapshot."""

    symbol: Symbol

    timestamp: datetime

    last_price: Decimal

    bid_price: Decimal | None = None
    ask_price: Decimal | None = None

    high_price_24h: Decimal | None = None
    low_price_24h: Decimal | None = None

    base_volume_24h: Decimal | None = None
    quote_volume_24h: Decimal | None = None

    def __post_init__(self) -> None:
        """Validate ticker data."""

        # ------------------------------------------------------------------
        # Timestamp
        # ------------------------------------------------------------------

        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")

        # ------------------------------------------------------------------
        # Prices
        # ------------------------------------------------------------------

        if self.last_price < _ZERO:
            raise ValueError("last_price must be >= 0")

        for name, value in (
            ("bid_price", self.bid_price),
            ("ask_price", self.ask_price),
            ("high_price_24h", self.high_price_24h),
            ("low_price_24h", self.low_price_24h),
        ):
            if value is not None and value < _ZERO:
                raise ValueError(f"{name} must be >= 0")

        if (
            self.bid_price is not None
            and self.ask_price is not None
            and self.bid_price > self.ask_price
        ):
            raise ValueError(
                "bid_price must be <= ask_price"
            )

        # ------------------------------------------------------------------
        # Volumes
        # ------------------------------------------------------------------

        for name, value in (
            ("base_volume_24h", self.base_volume_24h),
            ("quote_volume_24h", self.quote_volume_24h),
        ):
            if value is not None and value < _ZERO:
                raise ValueError(f"{name} must be >= 0")

    @property
    def has_orderbook(self) -> bool:
        """Return True if bid and ask prices are available."""

        return (
            self.bid_price is not None
            and self.ask_price is not None
        )

    @property
    def spread(self) -> Decimal | None:
        """Return bid-ask spread."""

        if not self.has_orderbook:
            return None

        return self.ask_price - self.bid_price