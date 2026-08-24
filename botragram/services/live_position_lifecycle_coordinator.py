"""
Botragram

Description:
    Serialize conflicting LIVE position lifecycle operations.

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
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

__all__ = [
    "LivePositionLifecycleCoordinator",
]


# =============================================================================
# Service Classes
# =============================================================================
class LivePositionLifecycleCoordinator:
    """Serialize LIVE protection ticks with natural-exit cleanup.

    One process-local lock intentionally covers the short critical sections that
    can mutate one durable LIVE position. The coordinator also versions deleted
    positions so a later market tick cannot reuse a stale local cache.
    """

    __slots__ = ("_lock", "_position_versions")

    def __init__(self) -> None:
        """Initialize an unlocked lifecycle coordinator."""
        self._lock = asyncio.Lock()
        self._position_versions: dict[str, int] = {}

    def get_position_version(self, *, symbol: str) -> int:
        """Return the current cache-invalidating lifecycle version for a symbol."""
        return self._position_versions.get(self._normalize_symbol(symbol), 0)

    def record_position_deletion(self, *, symbol: str) -> None:
        """Invalidate position caches after a durable natural-exit deletion."""
        normalized_symbol = self._normalize_symbol(symbol)
        self._position_versions[normalized_symbol] = (
            self._position_versions.get(normalized_symbol, 0) + 1
        )

    @asynccontextmanager
    async def hold(self, *, symbol: str) -> AsyncGenerator[None]:
        """Serialize one position lifecycle operation.

        Args:
            symbol: Position symbol retained for a validated call boundary.

        Yields:
            None while the lifecycle operation owns the coordinator.

        Raises:
            ValueError: If ``symbol`` is empty.
        """
        self._normalize_symbol(symbol)

        async with self._lock:
            yield

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize and validate one lifecycle symbol."""
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("LIVE position lifecycle symbol must not be empty")
        return normalized_symbol
