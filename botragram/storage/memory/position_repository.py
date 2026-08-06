"""
Botragram

Description:
    In-memory trading position repository implementation.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import PositionSide
from botragram.models import Position
from botragram.repositories import PositionRepository
from botragram.storage.base import BaseMemoryRepository

__all__ = [
    "MemoryPositionRepository",
]


# =============================================================================
# Repository Implementations
# =============================================================================
class MemoryPositionRepository(
    BaseMemoryRepository,
    PositionRepository,
):
    """Store trading positions in process memory."""

    __slots__ = ("_positions",)

    def __init__(self) -> None:
        """Initialize an empty position repository."""
        super().__init__()

        self._positions: dict[str, Position] = {}

    async def save(
        self,
        *,
        position: Position,
    ) -> None:
        """Persist or replace a trading position."""
        symbol = self._normalize_symbol(position.symbol)

        async with self._lock:
            self._positions[symbol] = position

    async def save_many(
        self,
        *,
        positions: Sequence[Position],
    ) -> None:
        """Persist or replace multiple trading positions."""
        records: dict[str, Position] = {
            self._normalize_symbol(position.symbol): position for position in positions
        }

        async with self._lock:
            self._positions.update(records)

    async def get_by_symbol(
        self,
        *,
        symbol: str,
    ) -> Position | None:
        """Return the active position for a trading symbol."""
        normalized_symbol = self._normalize_symbol(symbol)

        async with self._lock:
            return self._positions.get(normalized_symbol)

    async def get_all(
        self,
    ) -> Sequence[Position]:
        """Return all stored positions."""
        async with self._lock:
            positions = list(self._positions.values())

        positions.sort(
            key=lambda position: (
                position.symbol,
                position.opened_at,
            )
        )

        return tuple(positions)

    async def get_by_side(
        self,
        *,
        side: PositionSide,
    ) -> Sequence[Position]:
        """Return positions filtered by position side."""
        async with self._lock:
            positions: list[Position] = [
                position
                for position in self._positions.values()
                if position.side is side
            ]

        positions.sort(
            key=lambda position: (
                position.symbol,
                position.opened_at,
            )
        )

        return tuple(positions)

    async def get_open_positions(
        self,
    ) -> Sequence[Position]:
        """Return all active non-zero positions."""
        async with self._lock:
            positions: list[Position] = [
                position
                for position in self._positions.values()
                if position.quantity > 0
            ]

        positions.sort(
            key=lambda position: (
                position.symbol,
                position.opened_at,
            )
        )

        return tuple(positions)

    async def update(
        self,
        *,
        position: Position,
    ) -> None:
        """Update an existing position.

        Raises:
            LookupError: If the position does not exist.
        """
        symbol = self._normalize_symbol(position.symbol)

        async with self._lock:
            if symbol not in self._positions:
                raise LookupError(f"Position does not exist for symbol {symbol!r}")

            self._positions[symbol] = position

    async def delete(
        self,
        *,
        symbol: str,
    ) -> bool:
        """Delete a position by trading symbol."""
        normalized_symbol = self._normalize_symbol(symbol)

        async with self._lock:
            return (
                self._positions.pop(
                    normalized_symbol,
                    None,
                )
                is not None
            )

    async def delete_all(
        self,
    ) -> int:
        """Delete all stored positions."""
        async with self._lock:
            deleted_count = len(self._positions)
            self._positions.clear()

        return deleted_count

    async def count(
        self,
    ) -> int:
        """Return the number of stored positions."""
        async with self._lock:
            return len(self._positions)
