"""Persistence contract for closed Botragram position lifecycles."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from botragram.models import ClosedPositionLifecycle, PendingClosedPositionLifecycle

__all__ = ["ClosedPositionLifecycleRepository"]


class ClosedPositionLifecycleRepository(ABC):
    """Persist one idempotent closed trade per durable entry lifecycle."""

    __slots__ = ()

    @abstractmethod
    async def stage(self, *, lifecycle: PendingClosedPositionLifecycle) -> None:
        """Persist exact closure ownership without overwriting conflicting evidence."""

    @abstractmethod
    async def complete(self, *, lifecycle: ClosedPositionLifecycle) -> None:
        """Complete one staged lifecycle idempotently with authoritative finance."""

    @abstractmethod
    async def get_pending(self) -> Sequence[PendingClosedPositionLifecycle]:
        """Return staged lifecycles that still require financial enrichment."""

    @abstractmethod
    async def get_completed(self) -> Sequence[ClosedPositionLifecycle]:
        """Return every completed lifecycle ordered by authoritative close time."""

    @abstractmethod
    async def get_by_entry_client_order_id(
        self,
        *,
        entry_client_order_id: str,
    ) -> ClosedPositionLifecycle | PendingClosedPositionLifecycle | None:
        """Return one staged or completed lifecycle by canonical identity."""
