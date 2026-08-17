"""
Botragram

Description:
    Process-local execution authorization repository contract.

Python:
    3.14+
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from botragram.enums import AuthorizationStatus
from botragram.models import ExecutionAuthorization

__all__ = ["ExecutionAuthorizationRepository"]


class ExecutionAuthorizationRepository(ABC):
    """Own bounded, process-local pending execution authorizations."""

    __slots__ = ()

    @abstractmethod
    async def create(self, *, authorization: ExecutionAuthorization) -> None:
        """Store one pending authorization."""

    @abstractmethod
    async def get(self, *, authorization_id: str) -> ExecutionAuthorization | None:
        """Return one authorization by its opaque identifier."""

    @abstractmethod
    async def consume_pending(
        self,
        *,
        authorization_id: str,
        status: AuthorizationStatus,
        now: datetime,
    ) -> ExecutionAuthorization | None:
        """Atomically consume a pending authorization, or return none."""

    @abstractmethod
    async def count(self) -> int:
        """Return the bounded number of retained authorizations."""
