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
    can mutate one durable LIVE position. This prevents a stale market tick
    from updating a position while natural-exit reconciliation is proving and
    deleting that same position.
    """

    __slots__ = ("_lock",)

    def __init__(self) -> None:
        """Initialize an unlocked lifecycle coordinator."""
        self._lock = asyncio.Lock()

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
        if not symbol.strip():
            raise ValueError("LIVE position lifecycle symbol must not be empty")

        async with self._lock:
            yield
