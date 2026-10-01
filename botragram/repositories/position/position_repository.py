"""
Botragram

Description:
    Trading position repository interface.

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
from abc import ABC, abstractmethod
from collections.abc import Sequence

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import PositionSide
from botragram.models import Position

__all__ = [
    "PositionRepository",
]


# =============================================================================
# Abstract Repositories
# =============================================================================
class PositionRepository(ABC):
    """Abstract persistence interface for trading positions."""

    __slots__ = ()

    @abstractmethod
    async def save(
        self,
        *,
        position: Position,
    ) -> None:
        """Persist a trading position."""

    @abstractmethod
    async def save_many(
        self,
        *,
        positions: Sequence[Position],
    ) -> None:
        """Persist multiple trading positions."""

    @abstractmethod
    async def get_by_symbol(
        self,
        *,
        symbol: str,
    ) -> Position | None:
        """Return the active position for a trading symbol."""

    @abstractmethod
    async def get_all(self) -> Sequence[Position]:
        """Return all stored positions."""

    @abstractmethod
    async def get_by_side(
        self,
        *,
        side: PositionSide,
    ) -> Sequence[Position]:
        """Return positions filtered by position side."""

    @abstractmethod
    async def get_open_positions(self) -> Sequence[Position]:
        """Return all active positions."""

    @abstractmethod
    async def update(
        self,
        *,
        position: Position,
    ) -> None:
        """Update an existing position."""

    @abstractmethod
    async def delete(
        self,
        *,
        symbol: str,
    ) -> bool:
        """Delete a position by trading symbol.

        Returns:
            True if the position existed and was removed.
        """

    @abstractmethod
    async def delete_all(self) -> int:
        """Delete all stored positions.

        Returns:
            Number of deleted positions.
        """

    @abstractmethod
    async def count(self) -> int:
        """Return the number of stored positions."""
