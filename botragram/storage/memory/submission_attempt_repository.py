"""In-memory durable submission-attempt repository for tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from botragram.enums import SubmissionAttemptStatus
from botragram.models import SubmissionAttempt
from botragram.repositories import SubmissionAttemptRepository
from botragram.storage.base import BaseMemoryRepository

__all__ = ["MemorySubmissionAttemptRepository"]


class MemorySubmissionAttemptRepository(
    BaseMemoryRepository, SubmissionAttemptRepository
):
    """Store submission attempts in process memory."""

    __slots__ = ("_attempts",)

    def __init__(self) -> None:
        """Initialize empty attempt storage."""
        super().__init__()
        self._attempts: dict[str, SubmissionAttempt] = {}

    async def save(self, *, attempt: SubmissionAttempt) -> None:
        """Persist one immutable attempt."""
        async with self._lock:
            self._attempts[attempt.client_order_id] = attempt

    async def resolve_no_exposure(
        self,
        *,
        symbol: str,
        attempt: SubmissionAttempt,
    ) -> None:
        """Persist the terminal resolved-no-exposure state for one attempt."""
        del symbol
        async with self._lock:
            self._attempts[attempt.client_order_id] = replace(
                attempt,
                status=SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE,
                updated_at=datetime.now(UTC),
            )

    async def get_by_client_order_id(
        self, *, client_order_id: str
    ) -> SubmissionAttempt | None:
        """Return an attempt by client identity."""
        async with self._lock:
            return self._attempts.get(client_order_id)

    async def get_unresolved(self) -> Sequence[SubmissionAttempt]:
        """Return prepared or ambiguous attempts in creation order."""
        async with self._lock:
            attempts = tuple(
                attempt
                for attempt in self._attempts.values()
                if attempt.status
                in (
                    SubmissionAttemptStatus.PREPARED,
                    SubmissionAttemptStatus.UNRESOLVED,
                )
            )
        return tuple(sorted(attempts, key=lambda attempt: attempt.created_at))

    async def get_incomplete(self) -> Sequence[SubmissionAttempt]:
        """Return all attempts whose LIVE lifecycle is not terminally safe."""
        async with self._lock:
            attempts = tuple(
                attempt
                for attempt in self._attempts.values()
                if attempt.status
                in (
                    SubmissionAttemptStatus.PREPARED,
                    SubmissionAttemptStatus.UNRESOLVED,
                    SubmissionAttemptStatus.ACKNOWLEDGED,
                )
            )
        return tuple(sorted(attempts, key=lambda attempt: attempt.created_at))
