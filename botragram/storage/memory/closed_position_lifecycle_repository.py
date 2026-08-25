"""In-memory closed-position lifecycle repository for deterministic tests."""

from __future__ import annotations

from collections.abc import Sequence

from botragram.models import ClosedPositionLifecycle, PendingClosedPositionLifecycle
from botragram.repositories import ClosedPositionLifecycleRepository
from botragram.storage.base import BaseMemoryRepository

__all__ = ["MemoryClosedPositionLifecycleRepository"]


class MemoryClosedPositionLifecycleRepository(
    BaseMemoryRepository,
    ClosedPositionLifecycleRepository,
):
    """Store immutable lifecycle closure evidence by entry identity."""

    __slots__ = ("_records",)

    def __init__(self) -> None:
        """Initialize empty lifecycle storage."""
        super().__init__()
        self._records: dict[
            str,
            ClosedPositionLifecycle | PendingClosedPositionLifecycle,
        ] = {}

    async def stage(self, *, lifecycle: PendingClosedPositionLifecycle) -> None:
        """Insert exact ownership once and reject conflicting replay."""
        async with self._lock:
            existing = self._records.get(lifecycle.entry_client_order_id)
            if existing is None:
                self._records[lifecycle.entry_client_order_id] = lifecycle
                return
            ownership = (
                existing.ownership
                if isinstance(existing, ClosedPositionLifecycle)
                else existing
            )
            if ownership != lifecycle:
                raise RuntimeError("Closed lifecycle identity conflicts with storage")

    async def complete(self, *, lifecycle: ClosedPositionLifecycle) -> None:
        """Complete a matching staged lifecycle exactly once."""
        async with self._lock:
            existing = self._records.get(lifecycle.entry_client_order_id)
            if existing is None:
                raise RuntimeError("Closed lifecycle must be staged before completion")
            if isinstance(existing, ClosedPositionLifecycle):
                if existing != lifecycle:
                    raise RuntimeError(
                        "Completed lifecycle conflicts with authoritative storage"
                    )
                return
            if existing != lifecycle.ownership:
                raise RuntimeError("Closed lifecycle completion ownership conflicts")
            self._records[lifecycle.entry_client_order_id] = lifecycle

    async def get_pending(self) -> Sequence[PendingClosedPositionLifecycle]:
        """Return staged records in deterministic recording order."""
        async with self._lock:
            pending = tuple(
                record
                for record in self._records.values()
                if isinstance(record, PendingClosedPositionLifecycle)
            )
        return tuple(sorted(pending, key=lambda record: record.recorded_at))

    async def get_completed(self) -> Sequence[ClosedPositionLifecycle]:
        """Return completed lifecycles in authoritative close order."""
        async with self._lock:
            completed = tuple(
                record
                for record in self._records.values()
                if isinstance(record, ClosedPositionLifecycle)
            )
        return tuple(sorted(completed, key=lambda record: record.closed_at))

    async def get_by_entry_client_order_id(
        self,
        *,
        entry_client_order_id: str,
    ) -> ClosedPositionLifecycle | PendingClosedPositionLifecycle | None:
        """Return one lifecycle by its durable entry identity."""
        async with self._lock:
            return self._records.get(entry_client_order_id)
