"""Durable submission-attempt repository contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from botragram.models import SubmissionAttempt

__all__ = ["SubmissionAttemptRepository"]


class SubmissionAttemptRepository(ABC):
    """Persist pre-exchange LIVE entry identities."""

    @abstractmethod
    async def save(self, *, attempt: SubmissionAttempt) -> None:
        """Persist or replace one attempt."""

    @abstractmethod
    async def resolve_no_exposure(
        self,
        *,
        symbol: str,
        attempt: SubmissionAttempt,
    ) -> None:
        """Persist the terminal no-exposure state atomically for one symbol."""

    @abstractmethod
    async def get_by_client_order_id(
        self, *, client_order_id: str
    ) -> SubmissionAttempt | None:
        """Return one attempt by its durable client identity."""

    @abstractmethod
    async def get_unresolved(self) -> Sequence[SubmissionAttempt]:
        """Return attempts that still block a new LIVE entry."""

    @abstractmethod
    async def get_incomplete(self) -> Sequence[SubmissionAttempt]:
        """Return attempts requiring durable LIVE lifecycle recovery."""
