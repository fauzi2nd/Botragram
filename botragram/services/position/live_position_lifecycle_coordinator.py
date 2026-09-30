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
    """Serialize LIVE protection ticks with recovery and exit cleanup.

    One process-local lock intentionally covers safety-critical sections that
    can mutate durable LIVE position ownership. The coordinator also versions
    deleted positions so a later market tick cannot reuse a stale local cache.
    """

    __slots__ = ("_depth", "_lock", "_owner", "_position_versions")

    def __init__(self) -> None:
        """Initialize an unlocked lifecycle coordinator."""
        self._lock = asyncio.Lock()
        self._owner: object | None = None
        self._depth: int = 0
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

    async def _acquire(self) -> None:
        """Acquire the coordinator lock with task re-entrancy."""
        current = asyncio.current_task()
        if current is not None and self._owner is current:
            self._depth += 1
            return
        await self._lock.acquire()
        self._owner = current
        self._depth = 1

    def _release(self) -> None:
        """Release one depth level or the underlying coordinator lock."""
        current = asyncio.current_task()
        if current is not None and self._owner is not current:
            raise RuntimeError("Cannot release unowned lifecycle coordinator lock")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()

    @asynccontextmanager
    async def hold_portfolio(self) -> AsyncGenerator[None]:
        """Serialize one authoritative portfolio recovery.

        Yields:
            None while portfolio synchronization, persistence, and protection
            verification own the lifecycle coordinator.
        """
        await self._acquire()
        try:
            yield
        finally:
            self._release()

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
        await self._acquire()
        try:
            yield
        finally:
            self._release()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize and validate one lifecycle symbol."""
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("LIVE position lifecycle symbol must not be empty")
        return normalized_symbol
