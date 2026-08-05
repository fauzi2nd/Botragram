"""
Botragram

Description:
    Trading position application service.

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
from collections.abc import Sequence
from dataclasses import dataclass

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine import PositionEngine
from botragram.models import Position
from botragram.repositories import PositionRepository

__all__ = [
    "PositionService",
]


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class PositionService:
    """Manage trading positions."""

    position_engine: PositionEngine
    position_repository: PositionRepository

    async def sync(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Synchronize exchange positions into the repository.

        Args:
            symbol: Optional trading symbol filter.

        Returns:
            Synchronized positions.
        """
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        positions = await self.position_engine.get_positions(
            symbol=normalized_symbol,
        )

        await self.position_repository.save_many(
            positions=positions,
        )

        return positions

    async def get(
        self,
        *,
        symbol: str,
        synchronize: bool = False,
    ) -> Position | None:
        """Return a position for a trading symbol.

        Args:
            symbol: Trading pair symbol.
            synchronize: Refresh from exchange before reading.

        Returns:
            Matching position, or None.
        """
        normalized_symbol = self._normalize_symbol(symbol)

        if synchronize:
            await self.sync(
                symbol=normalized_symbol,
            )

        return await self.position_repository.get_by_symbol(
            symbol=normalized_symbol,
        )

    async def get_all(
        self,
        *,
        synchronize: bool = False,
    ) -> Sequence[Position]:
        """Return all positions.

        Args:
            synchronize: Refresh from exchange before reading.

        Returns:
            Stored positions.
        """
        if synchronize:
            await self.sync()

        return await self.position_repository.get_all()

    async def has_position(
        self,
        *,
        symbol: str,
        synchronize: bool = False,
    ) -> bool:
        """Return whether an active position exists."""
        position = await self.get(
            symbol=symbol,
            synchronize=synchronize,
        )

        return position is not None

    async def delete(
        self,
        *,
        symbol: str,
    ) -> bool:
        """Delete a stored position."""
        return await self.position_repository.delete(
            symbol=self._normalize_symbol(symbol),
        )

    async def clear(self) -> int:
        """Delete every stored position."""
        return await self.position_repository.delete_all()

    async def count(self) -> int:
        """Return the number of stored positions."""
        return await self.position_repository.count()

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol
