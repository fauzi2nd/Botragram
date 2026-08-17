"""SQLite durable submission-attempt repository implementation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from sqlite3 import Row

from botragram.enums import (
    Interval,
    OrderSide,
    OrderType,
    StrategyType,
    SubmissionAttemptStatus,
)
from botragram.models import SubmissionAttempt
from botragram.repositories import SubmissionAttemptRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = ["SQLiteSubmissionAttemptRepository"]


_COLUMNS = """client_order_id, symbol, side, order_type, quantity,
signal_generated_at, interval, strategy_type, status, exchange_order_id,
created_at, updated_at"""
_DATETIME_ERROR_TEMPLATE = "SQLite submission attempt {label} must be timezone-aware"
_UPSERT = f"""INSERT INTO submission_attempts ({_COLUMNS}) VALUES
(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(client_order_id) DO UPDATE SET status=excluded.status,
exchange_order_id=excluded.exchange_order_id, updated_at=excluded.updated_at;"""


class SQLiteSubmissionAttemptRepository(SubmissionAttemptRepository):
    """Persist durable LIVE submission attempts in SQLite."""

    __slots__ = ("_database",)

    def __init__(self, *, database: SQLiteDatabase) -> None:
        """Initialize the repository with one connected database."""
        self._database = database

    async def save(self, *, attempt: SubmissionAttempt) -> None:
        """Persist or replace one attempt lifecycle snapshot."""
        await self._database.execute(
            statement=_UPSERT, parameters=self._params(attempt)
        )

    async def get_by_client_order_id(
        self, *, client_order_id: str
    ) -> SubmissionAttempt | None:
        """Return one attempt by its durable client identity."""
        row = await self._database.fetch_one(
            statement=(
                f"SELECT {_COLUMNS} FROM submission_attempts WHERE client_order_id = ?;"
            ),
            parameters=(client_order_id,),
        )
        return self._from_row(row) if row is not None else None

    async def get_unresolved(self) -> Sequence[SubmissionAttempt]:
        """Return attempts that must block another LIVE mutation."""
        rows = await self._database.fetch_all(
            statement=(
                f"SELECT {_COLUMNS} FROM submission_attempts "
                "WHERE status IN (?, ?) ORDER BY created_at ASC;"
            ),
            parameters=(
                SubmissionAttemptStatus.PREPARED.value,
                SubmissionAttemptStatus.UNRESOLVED.value,
            ),
        )
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def _params(attempt: SubmissionAttempt) -> tuple[object, ...]:
        """Serialize one immutable attempt."""
        return (
            attempt.client_order_id,
            attempt.symbol,
            attempt.side.value,
            attempt.order_type.value,
            str(attempt.quantity),
            attempt.signal_generated_at.isoformat(),
            attempt.interval.value,
            attempt.strategy_type.value if attempt.strategy_type else None,
            attempt.status.value,
            attempt.exchange_order_id,
            attempt.created_at.isoformat(),
            attempt.updated_at.isoformat(),
        )

    @staticmethod
    def _from_row(row: Row) -> SubmissionAttempt:
        """Reconstruct a strictly typed attempt from one SQLite row."""
        strategy = row["strategy_type"]
        return SubmissionAttempt(
            client_order_id=str(row["client_order_id"]),
            symbol=str(row["symbol"]),
            side=OrderSide(str(row["side"])),
            order_type=OrderType(str(row["order_type"])),
            quantity=Decimal(str(row["quantity"])),
            signal_generated_at=SQLiteSubmissionAttemptRepository._get_datetime(
                row,
                column="signal_generated_at",
            ),
            interval=Interval(str(row["interval"])),
            strategy_type=StrategyType(str(strategy)) if strategy is not None else None,
            status=SubmissionAttemptStatus(str(row["status"])),
            exchange_order_id=str(row["exchange_order_id"])
            if row["exchange_order_id"] is not None
            else None,
            created_at=SQLiteSubmissionAttemptRepository._get_datetime(
                row,
                column="created_at",
            ),
            updated_at=SQLiteSubmissionAttemptRepository._get_datetime(
                row,
                column="updated_at",
            ),
        )

    @staticmethod
    def _get_datetime(row: Row, *, column: str) -> datetime:
        """Return one timezone-aware SQLite datetime column."""
        value = datetime.fromisoformat(str(row[column]))

        if value.tzinfo is None:
            raise ValueError(_DATETIME_ERROR_TEMPLATE.format(label=column))

        return value
