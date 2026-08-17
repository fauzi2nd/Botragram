"""
Botragram

Description:
    Bounded in-memory execution authorization repository.

Python:
    3.14+
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Final

from botragram.enums import AuthorizationStatus
from botragram.models import ExecutionAuthorization
from botragram.repositories import ExecutionAuthorizationRepository
from botragram.storage.base import BaseMemoryRepository

__all__ = ["MemoryExecutionAuthorizationRepository"]

_DEFAULT_MAXIMUM_AUTHORIZATIONS: Final[int] = 100


class MemoryExecutionAuthorizationRepository(
    BaseMemoryRepository,
    ExecutionAuthorizationRepository,
):
    """Retain a bounded authorization lifecycle for one process only."""

    __slots__ = ("_authorizations", "_maximum_authorizations")

    def __init__(
        self,
        *,
        maximum_authorizations: int = _DEFAULT_MAXIMUM_AUTHORIZATIONS,
    ) -> None:
        """Initialize bounded process-local authorization storage."""
        super().__init__()

        if maximum_authorizations <= 0:
            raise ValueError("Maximum authorizations must be greater than zero")

        self._maximum_authorizations = maximum_authorizations
        self._authorizations: dict[str, ExecutionAuthorization] = {}

    async def create(self, *, authorization: ExecutionAuthorization) -> None:
        """Store a new pending authorization within the configured bound."""
        if authorization.status is not AuthorizationStatus.PENDING:
            raise ValueError("New execution authorization must be pending")

        async with self._lock:
            self._prune_terminal()

            if authorization.authorization_id in self._authorizations:
                raise RuntimeError("Execution authorization identifier already exists")

            if len(self._authorizations) >= self._maximum_authorizations:
                raise RuntimeError("Execution authorization capacity reached")

            self._authorizations[authorization.authorization_id] = authorization

    async def create_if_no_equivalent_pending(
        self,
        *,
        authorization: ExecutionAuthorization,
    ) -> bool:
        """Atomically store one authorization when no equivalent item is pending."""
        if authorization.status is not AuthorizationStatus.PENDING:
            raise ValueError("New execution authorization must be pending")

        async with self._lock:
            self._expire_and_prune(now=datetime.now(UTC))

            if any(
                existing.status is AuthorizationStatus.PENDING
                and self._is_equivalent_candidate(
                    first=existing,
                    second=authorization,
                )
                for existing in self._authorizations.values()
            ):
                return False

            if authorization.authorization_id in self._authorizations:
                raise RuntimeError("Execution authorization identifier already exists")

            if len(self._authorizations) >= self._maximum_authorizations:
                raise RuntimeError("Execution authorization capacity reached")

            self._authorizations[authorization.authorization_id] = authorization
            return True

    async def get(self, *, authorization_id: str) -> ExecutionAuthorization | None:
        """Return one authorization without consuming it."""
        normalized_identifier = self._normalize_identifier(
            authorization_id,
            label="Execution authorization",
        )

        async with self._lock:
            self._expire_and_prune(now=datetime.now(UTC))
            return self._authorizations.get(normalized_identifier)

    async def consume_pending(
        self,
        *,
        authorization_id: str,
        status: AuthorizationStatus,
        now: datetime,
    ) -> ExecutionAuthorization | None:
        """Atomically transition a pending authorization to a terminal state."""
        if status not in (AuthorizationStatus.APPROVED, AuthorizationStatus.REJECTED):
            raise ValueError("Authorization consumption requires approval or rejection")

        normalized_identifier = self._normalize_identifier(
            authorization_id,
            label="Execution authorization",
        )

        async with self._lock:
            authorization = self._authorizations.get(normalized_identifier)

            if authorization is None:
                return None

            if authorization.status is not AuthorizationStatus.PENDING:
                return None

            if now >= authorization.expires_at:
                expired = replace(authorization, status=AuthorizationStatus.EXPIRED)
                self._authorizations[normalized_identifier] = expired
                return expired

            consumed = replace(authorization, status=status)
            self._authorizations[normalized_identifier] = consumed
            return consumed

    async def count(self) -> int:
        """Return the retained authorization count."""
        async with self._lock:
            self._expire_and_prune(now=datetime.now(UTC))
            return len(self._authorizations)

    def _expire_and_prune(self, *, now: datetime) -> None:
        """Expire pending records and prune oldest terminal records for capacity."""
        for authorization_id, authorization in tuple(self._authorizations.items()):
            if (
                authorization.status is AuthorizationStatus.PENDING
                and now >= authorization.expires_at
            ):
                self._authorizations[authorization_id] = replace(
                    authorization,
                    status=AuthorizationStatus.EXPIRED,
                )

        while len(self._authorizations) >= self._maximum_authorizations:
            if not self._prune_terminal():
                return

    def _prune_terminal(self) -> bool:
        """Remove one oldest terminal record when storage is at capacity."""
        if len(self._authorizations) < self._maximum_authorizations:
            return False

        terminal_identifier = next(
            (
                authorization_id
                for authorization_id, authorization in self._authorizations.items()
                if authorization.status is not AuthorizationStatus.PENDING
            ),
            None,
        )

        if terminal_identifier is None:
            return False

        del self._authorizations[terminal_identifier]
        return True

    @staticmethod
    def _is_equivalent_candidate(
        *,
        first: ExecutionAuthorization,
        second: ExecutionAuthorization,
    ) -> bool:
        """Compare the stable discovery identity used to suppress pending spam."""
        first_signal = first.signal
        second_signal = second.signal
        return (
            first_signal.symbol == second_signal.symbol
            and first_signal.signal_type is second_signal.signal_type
            and first_signal.strategy_name == second_signal.strategy_name
        )
