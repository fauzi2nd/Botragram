"""Durable operator-exit operation and attempt repository contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from botragram.models.operator_exit import OperatorExitAttempt, OperatorExitOperation

__all__ = ["OperatorExitRepository"]


class OperatorExitRepository(ABC):
    """Persist confirmed operator exits independently from entry attempts."""

    @abstractmethod
    async def reserve_operation(self, *, operation: OperatorExitOperation) -> bool:
        """Atomically reserve the sole incomplete operator portfolio action."""

    @abstractmethod
    async def save_operation(self, *, operation: OperatorExitOperation) -> None:
        """Persist or replace one operation state."""

    @abstractmethod
    async def get_operation(
        self, *, operation_id: str
    ) -> OperatorExitOperation | None:
        """Return one operation by its durable identity."""

    @abstractmethod
    async def get_incomplete_operations(self) -> Sequence[OperatorExitOperation]:
        """Return operations that still block entry and mode switching."""

    @abstractmethod
    async def get_latest_operation(self) -> OperatorExitOperation | None:
        """Return the most recently updated operation for observability."""

    @abstractmethod
    async def reserve_attempt(self, *, attempt: OperatorExitAttempt) -> bool:
        """Atomically reserve one incomplete LIVE close identity."""

    @abstractmethod
    async def save_attempt(self, *, attempt: OperatorExitAttempt) -> None:
        """Persist or replace one LIVE close attempt state."""

    @abstractmethod
    async def get_attempt_by_client_order_id(
        self, *, client_order_id: str
    ) -> OperatorExitAttempt | None:
        """Return one attempt by exact exchange client identity."""

    @abstractmethod
    async def get_incomplete_attempts(self) -> Sequence[OperatorExitAttempt]:
        """Return LIVE close attempts requiring GET-only recovery."""
