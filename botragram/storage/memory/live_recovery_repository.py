"""In-memory LiveRecoveryRepository implementation for tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Protocol

from botragram.models import SubmissionAttempt
from botragram.repositories import (
    PositionRepository,
    SubmissionAttemptRepository,
)
from botragram.repositories.live_recovery_repository import LiveRecoveryRepository


class PositionDeleter(Protocol):
    async def delete(self, *, symbol: str) -> bool: ...


class MemoryLiveRecoveryRepository(LiveRecoveryRepository):
    __slots__ = ("_attempt_repo", "_position_repo", "_lock")

    def __init__(
        self,
        *,
        attempt_repo: SubmissionAttemptRepository,
        position_repo: PositionRepository | PositionDeleter,
    ) -> None:
        self._attempt_repo = attempt_repo
        self._position_repo = position_repo
        self._lock = asyncio.Lock()

    async def resolve_no_exposure(
        self, *, symbol: str, attempt: SubmissionAttempt
    ) -> None:
        resolved = replace(
            attempt,
            status=attempt.status.__class__.RESOLVED_NO_EXPOSURE,
        )

        async with self._lock:
            # perform delete then upsert under one in-memory lock to emulate
            # atomic behavior visible to callers.
            await self._position_repo.delete(symbol=symbol)
            await self._attempt_repo.save(attempt=resolved)
