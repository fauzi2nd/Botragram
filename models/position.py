"""
Trading Bot

Module:
    models.position

Description:
    Domain model representing an open trading position.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from models.enums import (
    ExchangeType,
    MarginMode,
    PositionSide,
)
from models.symbol import Symbol

__all__ = [
    "Position",
]

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass(slots=True, frozen=True)
class Position:
    """Represents an open trading position."""

    exchange: ExchangeType
    symbol: Symbol

    position_side: PositionSide
    margin_mode: MarginMode

    quantity: Decimal

    entry_price: Decimal
    mark_price: Decimal
    liquidation_price: Decimal | None

    leverage: Decimal

    unrealized_pnl: Decimal

    timestamp: datetime

    def __post_init__(self) -> None:
        """Validate position."""

        # ------------------------------------------------------------------
        # Timestamp
        # ------------------------------------------------------------------

        if self.timestamp.tzinfo is None:
            raise ValueError(
                "timestamp must be timezone-aware"
            )

        # ------------------------------------------------------------------
        # Position
        # ------------------------------------------------------------------

        if self.quantity <= _ZERO:
            raise ValueError("quantity must be > 0")

        if self.entry_price <= _ZERO:
            raise ValueError("entry_price must be > 0")

        if self.mark_price <= _ZERO:
            raise ValueError("mark_price must be > 0")

        if (
            self.liquidation_price is not None
            and self.liquidation_price <= _ZERO
        ):
            raise ValueError(
                "liquidation_price must be > 0"
            )

        if self.leverage < _ONE:
            raise ValueError(
                "leverage must be >= 1"
            )

    @property
    def is_long(self) -> bool:
        """Return True if the position is long."""

        return self.position_side is PositionSide.LONG

    @property
    def is_short(self) -> bool:
        """Return True if the position is short."""

        return self.position_side is PositionSide.SHORT