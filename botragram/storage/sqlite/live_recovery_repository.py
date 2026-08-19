"""SQLite LiveRecoveryRepository adapter that uses the SQLite repositories."""

from __future__ import annotations

from botragram.models import SubmissionAttempt
from botragram.repositories.live_recovery_repository import LiveRecoveryRepository
from botragram.storage.sqlite.submission_attempt_repository import (
    SQLiteSubmissionAttemptRepository,
)


class SQLiteLiveRecoveryRepository(LiveRecoveryRepository):
    __slots__ = ("_subrepo",)

    def __init__(self, *, subrepo: SQLiteSubmissionAttemptRepository) -> None:
        self._subrepo = subrepo

    async def resolve_no_exposure(
        self, *, symbol: str, attempt: SubmissionAttempt
    ) -> None:
        # Delegate to the SQLite-specific repository method which performs
        # the DELETE + UPSERT inside a single SQLite transaction.
        await self._subrepo.resolve_no_exposure(symbol=symbol, attempt=attempt)
