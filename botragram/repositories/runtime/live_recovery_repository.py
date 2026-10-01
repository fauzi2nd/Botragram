"""Repository abstraction for authoritative LIVE recovery atomic operations.

This narrow abstraction guarantees a single caller-visible atomic operation
that both persists the terminal submission-attempt state and removes the
stale persisted Position in one logical step.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from botragram.models import SubmissionAttempt

__all__ = ["LiveRecoveryRepository"]


class LiveRecoveryRepository(ABC):
    """Storage-agnostic atomic recovery operations used by services."""

    @abstractmethod
    async def resolve_no_exposure(
        self, *, symbol: str, attempt: SubmissionAttempt
    ) -> None:
        """Atomically persist terminal RESOLVED_NO_EXPOSURE and clear Position.

        On success: attempt persisted as RESOLVED_NO_EXPOSURE and any stale
        persisted Position for `symbol` is removed.

        On failure: no durable mutation is performed (caller-visible state
        remains unchanged).
        """
        ...
