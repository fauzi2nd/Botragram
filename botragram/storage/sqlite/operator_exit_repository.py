"""SQLite operator-exit operation and attempt repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from sqlite3 import Row

from botragram.enums import (
    ExecutionPolicy,
    OperatorExitAttemptStatus,
    OperatorExitStatus,
    OperatorExitType,
    PositionSide,
)
from botragram.models import OperatorExitAttempt, OperatorExitOperation
from botragram.repositories import OperatorExitRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = ["SQLiteOperatorExitRepository"]


_OPERATION_COLUMNS = """operation_id, operation_type, status, requested_by,
symbol, authorized_symbols, target_execution_policy, failure_reason, created_at,
updated_at"""
_ATTEMPT_COLUMNS = """client_order_id, operation_id, symbol, position_side,
quantity, status, exchange_order_id, failure_reason, created_at, updated_at"""
_OPERATION_UPSERT = f"""INSERT INTO operator_exit_operations
({_OPERATION_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(operation_id) DO UPDATE SET status=excluded.status,
failure_reason=excluded.failure_reason, updated_at=excluded.updated_at;"""
_ATTEMPT_UPSERT = f"""INSERT INTO operator_exit_attempts
({_ATTEMPT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(client_order_id) DO UPDATE SET status=excluded.status,
exchange_order_id=excluded.exchange_order_id,
failure_reason=excluded.failure_reason, updated_at=excluded.updated_at;"""
_INCOMPLETE_OPERATION_STATUSES = (
    OperatorExitStatus.FLATTENING,
    OperatorExitStatus.RECOVERY_REQUIRED,
    OperatorExitStatus.RECONCILING,
    OperatorExitStatus.SWITCH_PENDING,
)


class SQLiteOperatorExitRepository(OperatorExitRepository):
    """Persist restart-safe operator portfolio actions in SQLite."""

    __slots__ = ("_database",)

    def __init__(self, *, database: SQLiteDatabase) -> None:
        """Initialize the repository with one connected database."""
        self._database = database

    async def reserve_operation(self, *, operation: OperatorExitOperation) -> bool:
        """Atomically reserve the sole incomplete operator operation."""
        affected_rows = await self._database.execute(
            statement=f"""INSERT INTO operator_exit_operations
({_OPERATION_COLUMNS})
SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1 FROM operator_exit_operations WHERE status IN (?, ?, ?, ?)
);""",
            parameters=(
                *self._operation_params(operation),
                *(status.value for status in _INCOMPLETE_OPERATION_STATUSES),
            ),
        )
        if affected_rows not in {0, 1}:
            raise RuntimeError("SQLite operator-exit reservation affected invalid rows")
        return affected_rows == 1

    async def save_operation(self, *, operation: OperatorExitOperation) -> None:
        """Persist one operation snapshot."""
        await self._database.execute(
            statement=_OPERATION_UPSERT,
            parameters=self._operation_params(operation),
        )

    async def get_operation(self, *, operation_id: str) -> OperatorExitOperation | None:
        """Return one operation by durable identity."""
        row = await self._database.fetch_one(
            statement=(
                f"SELECT {_OPERATION_COLUMNS} FROM operator_exit_operations "
                "WHERE operation_id = ?;"
            ),
            parameters=(operation_id,),
        )
        return self._operation_from_row(row) if row is not None else None

    async def get_incomplete_operations(self) -> Sequence[OperatorExitOperation]:
        """Return operations that still own the financial boundary."""
        rows = await self._database.fetch_all(
            statement=(
                f"SELECT {_OPERATION_COLUMNS} FROM operator_exit_operations "
                "WHERE status IN (?, ?, ?, ?) ORDER BY created_at ASC;"
            ),
            parameters=tuple(status.value for status in _INCOMPLETE_OPERATION_STATUSES),
        )
        return tuple(self._operation_from_row(row) for row in rows)

    async def get_latest_operation(self) -> OperatorExitOperation | None:
        """Return the latest operation for operator observability."""
        row = await self._database.fetch_one(
            statement=(
                f"SELECT {_OPERATION_COLUMNS} FROM operator_exit_operations "
                "ORDER BY updated_at DESC LIMIT 1;"
            )
        )
        return self._operation_from_row(row) if row is not None else None

    async def reserve_attempt(self, *, attempt: OperatorExitAttempt) -> bool:
        """Atomically reserve the sole incomplete LIVE close attempt."""
        affected_rows = await self._database.execute(
            statement=f"""INSERT INTO operator_exit_attempts
({_ATTEMPT_COLUMNS})
SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1 FROM operator_exit_attempts WHERE status NOT IN (?, ?)
);""",
            parameters=(
                *self._attempt_params(attempt),
                OperatorExitAttemptStatus.COMPLETED.value,
                OperatorExitAttemptStatus.REJECTED.value,
            ),
        )
        if affected_rows not in {0, 1}:
            raise RuntimeError("SQLite operator-exit attempt affected invalid rows")
        return affected_rows == 1

    async def save_attempt(self, *, attempt: OperatorExitAttempt) -> None:
        """Persist one LIVE close attempt snapshot."""
        await self._database.execute(
            statement=_ATTEMPT_UPSERT,
            parameters=self._attempt_params(attempt),
        )

    async def get_attempt_by_client_order_id(
        self, *, client_order_id: str
    ) -> OperatorExitAttempt | None:
        """Return one attempt by exact client identity."""
        row = await self._database.fetch_one(
            statement=(
                f"SELECT {_ATTEMPT_COLUMNS} FROM operator_exit_attempts "
                "WHERE client_order_id = ?;"
            ),
            parameters=(client_order_id,),
        )
        return self._attempt_from_row(row) if row is not None else None

    async def get_incomplete_attempts(self) -> Sequence[OperatorExitAttempt]:
        """Return close attempts requiring authoritative reconciliation."""
        rows = await self._database.fetch_all(
            statement=(
                f"SELECT {_ATTEMPT_COLUMNS} FROM operator_exit_attempts "
                "WHERE status NOT IN (?, ?) ORDER BY created_at ASC;"
            ),
            parameters=(
                OperatorExitAttemptStatus.COMPLETED.value,
                OperatorExitAttemptStatus.REJECTED.value,
            ),
        )
        return tuple(self._attempt_from_row(row) for row in rows)

    @staticmethod
    def _operation_params(operation: OperatorExitOperation) -> tuple[object, ...]:
        return (
            operation.operation_id,
            operation.operation_type.value,
            operation.status.value,
            operation.requested_by,
            operation.symbol,
            "|".join(operation.authorized_symbols),
            (
                operation.target_execution_policy.value
                if operation.target_execution_policy is not None
                else None
            ),
            operation.failure_reason,
            operation.created_at.isoformat(),
            operation.updated_at.isoformat(),
        )

    @staticmethod
    def _attempt_params(attempt: OperatorExitAttempt) -> tuple[object, ...]:
        return (
            attempt.client_order_id,
            attempt.operation_id,
            attempt.symbol,
            attempt.position_side.value,
            str(attempt.quantity),
            attempt.status.value,
            attempt.exchange_order_id,
            attempt.failure_reason,
            attempt.created_at.isoformat(),
            attempt.updated_at.isoformat(),
        )

    @classmethod
    def _operation_from_row(cls, row: Row) -> OperatorExitOperation:
        target = row["target_execution_policy"]
        return OperatorExitOperation(
            operation_id=str(row["operation_id"]),
            operation_type=OperatorExitType(str(row["operation_type"])),
            status=OperatorExitStatus(str(row["status"])),
            requested_by=str(row["requested_by"]),
            symbol=str(row["symbol"]) if row["symbol"] is not None else None,
            authorized_symbols=tuple(
                symbol for symbol in str(row["authorized_symbols"]).split("|") if symbol
            ),
            target_execution_policy=(
                ExecutionPolicy(str(target)) if target is not None else None
            ),
            failure_reason=(
                str(row["failure_reason"])
                if row["failure_reason"] is not None
                else None
            ),
            created_at=cls._datetime(row=row, column="created_at"),
            updated_at=cls._datetime(row=row, column="updated_at"),
        )

    @classmethod
    def _attempt_from_row(cls, row: Row) -> OperatorExitAttempt:
        return OperatorExitAttempt(
            client_order_id=str(row["client_order_id"]),
            operation_id=str(row["operation_id"]),
            symbol=str(row["symbol"]),
            position_side=PositionSide(str(row["position_side"])),
            quantity=Decimal(str(row["quantity"])),
            status=OperatorExitAttemptStatus(str(row["status"])),
            exchange_order_id=(
                str(row["exchange_order_id"])
                if row["exchange_order_id"] is not None
                else None
            ),
            failure_reason=(
                str(row["failure_reason"])
                if row["failure_reason"] is not None
                else None
            ),
            created_at=cls._datetime(row=row, column="created_at"),
            updated_at=cls._datetime(row=row, column="updated_at"),
        )

    @staticmethod
    def _datetime(*, row: Row, column: str) -> datetime:
        value = datetime.fromisoformat(str(row[column]))
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError(f"SQLite operator-exit {column} must be timezone-aware")
        return value
