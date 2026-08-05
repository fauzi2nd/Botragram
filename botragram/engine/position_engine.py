"""
Botragram

Description:
    Trading position management engine.

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
from collections.abc import Sequence
from dataclasses import dataclass

# =============================================================================
# Local Imports
# =============================================================================
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Position

__all__ = [
    "PositionEngine",
]


# =============================================================================
# Position Engine
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class PositionEngine:
    """Query and inspect trading positions through an exchange client."""

    exchange_client: BaseExchangeClient

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Return active exchange positions.

        Args:
            symbol: Optional trading symbol filter.

        Returns:
            Active positions returned by the exchange.
        """
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        return await self.exchange_client.get_positions(
            symbol=normalized_symbol,
        )

    async def get_position(
        self,
        *,
        symbol: str,
    ) -> Position | None:
        """Return the active position for a symbol.

        Args:
            symbol: Trading pair symbol.

        Returns:
            Matching active position, or None if no position exists.

        Raises:
            RuntimeError: If the exchange returns multiple positions for
                the same symbol.
        """
        normalized_symbol = self._normalize_symbol(symbol)

        positions = await self.get_positions(
            symbol=normalized_symbol,
        )

        matching_position: Position | None = None

        for position in positions:
            if position.symbol.upper() != normalized_symbol:
                continue

            if matching_position is not None:
                raise RuntimeError(
                    "Exchange returned multiple positions for symbol "
                    f"{normalized_symbol!r}"
                )

            matching_position = position

        return matching_position

    async def has_open_position(
        self,
        *,
        symbol: str,
    ) -> bool:
        """Return whether an active position exists for a symbol.

        Args:
            symbol: Trading pair symbol.

        Returns:
            True when an active non-zero position exists.
        """
        position = await self.get_position(
            symbol=symbol,
        )

        return position is not None and position.quantity > 0

    async def require_position(
        self,
        *,
        symbol: str,
    ) -> Position:
        """Return an active position or raise an error.

        Args:
            symbol: Trading pair symbol.

        Returns:
            Active position for the symbol.

        Raises:
            LookupError: If no active position exists.
        """
        normalized_symbol = self._normalize_symbol(symbol)

        position = await self.get_position(
            symbol=normalized_symbol,
        )

        if position is None:
            raise LookupError(
                f"No active position found for symbol {normalized_symbol!r}"
            )

        return position

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol
