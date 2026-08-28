"""In-memory operator-exit repository implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from botragram.enums import OperatorExitAttemptStatus, OperatorExitStatus
from botragram.models import OperatorExitAttempt, OperatorExitOperation
from botragram.repositories import OperatorExitRepository

__all__ = ["MemoryOperatorExitRepository"]


_INCOMPLETE_OPERATION_STATUSES = frozenset(
    {
        OperatorExitStatus.FLATTENING,
        OperatorExitStatus.RECOVERY_REQUIRED,
        OperatorExitStatus.RECONCILING,
    }
)


class MemoryOperatorExitRepository(OperatorExitRepository):
    """Persist operator exits for deterministic application-service tests."""

    __slots__ = ("_attempts", "_lock", "_operations")

    def __init__(self) -> None:
        """Initialize empty operation and attempt stores."""
        self._operations: dict[str, OperatorExitOperation] = {}
        self._attempts: dict[str, OperatorExitAttempt] = {}
        self._lock = asyncio.Lock()

    async def reserve_operation(self, *, operation: OperatorExitOperation) -> bool:
        """Reserve an operation when no incomplete operation exists."""
        async with self._lock:
            if any(
                current.status in _INCOMPLETE_OPERATION_STATUSES
                for current in self._operations.values()
            ):
                return False
            if operation.operation_id in self._operations:
                return False
            self._operations[operation.operation_id] = operation
            return True

    async def save_operation(self, *, operation: OperatorExitOperation) -> None:
        """Persist one operation snapshot."""
        async with self._lock:
            self._operations[operation.operation_id] = operation

    async def get_operation(self, *, operation_id: str) -> OperatorExitOperation | None:
        """Return one operation by identity."""
        async with self._lock:
            return self._operations.get(operation_id)

    async def get_incomplete_operations(self) -> Sequence[OperatorExitOperation]:
        """Return incomplete operations in deterministic creation order."""
        async with self._lock:
            operations = tuple(
                operation
                for operation in self._operations.values()
                if operation.status in _INCOMPLETE_OPERATION_STATUSES
            )
        return tuple(sorted(operations, key=lambda item: item.created_at))

    async def get_latest_operation(self) -> OperatorExitOperation | None:
        """Return the most recently updated operation."""
        async with self._lock:
            return max(
                self._operations.values(),
                key=lambda item: item.updated_at,
                default=None,
            )

    async def reserve_attempt(self, *, attempt: OperatorExitAttempt) -> bool:
        """Reserve an attempt when no incomplete attempt exists."""
        async with self._lock:
            if any(
                current.status
                not in {
                    OperatorExitAttemptStatus.COMPLETED,
                    OperatorExitAttemptStatus.REJECTED,
                }
                for current in self._attempts.values()
            ):
                return False
            if attempt.client_order_id in self._attempts:
                return False
            self._attempts[attempt.client_order_id] = attempt
            return True

    async def save_attempt(self, *, attempt: OperatorExitAttempt) -> None:
        """Persist one attempt snapshot."""
        async with self._lock:
            self._attempts[attempt.client_order_id] = attempt

    async def get_attempt_by_client_order_id(
        self, *, client_order_id: str
    ) -> OperatorExitAttempt | None:
        """Return one attempt by exact client identity."""
        async with self._lock:
            return self._attempts.get(client_order_id)

    async def get_incomplete_attempts(self) -> Sequence[OperatorExitAttempt]:
        """Return attempts not yet reconciled to terminal safety."""
        async with self._lock:
            attempts = tuple(
                attempt
                for attempt in self._attempts.values()
                if attempt.status
                not in {
                    OperatorExitAttemptStatus.COMPLETED,
                    OperatorExitAttemptStatus.REJECTED,
                }
            )
        return tuple(sorted(attempts, key=lambda item: item.created_at))
