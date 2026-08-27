"""SQLite persistence for durable runtime canary limits."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from sqlite3 import Row
from typing import Final

from botragram.models import RuntimeRiskLimits
from botragram.repositories import RuntimeRiskLimitRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = ["SQLiteRuntimeRiskLimitRepository"]


_SCOPE: Final[str] = "active"
_SELECT_SQL: Final[str] = """
SELECT max_open_positions, max_position_size_usdt, updated_at, updated_by
FROM runtime_risk_limits
WHERE scope = ?;
"""
_UPSERT_SQL: Final[str] = """
INSERT INTO runtime_risk_limits (
    scope, max_open_positions, max_position_size_usdt, updated_at, updated_by
)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (scope) DO UPDATE SET
    max_open_positions = excluded.max_open_positions,
    max_position_size_usdt = excluded.max_position_size_usdt,
    updated_at = excluded.updated_at,
    updated_by = excluded.updated_by;
"""
_INSERT_EVENT_SQL: Final[str] = """
INSERT INTO runtime_risk_limit_events (
    max_open_positions, max_position_size_usdt, updated_at, updated_by
)
VALUES (?, ?, ?, ?);
"""


class SQLiteRuntimeRiskLimitRepository(RuntimeRiskLimitRepository):
    """Store current runtime limits with an append-only audit trail."""

    __slots__ = ("_database",)

    def __init__(self, *, database: SQLiteDatabase) -> None:
        """Initialize the repository with a connected database."""
        self._database = database

    async def get(self) -> RuntimeRiskLimits | None:
        """Return the latest durable runtime limits, if configured."""
        row = await self._database.fetch_one(
            statement=_SELECT_SQL,
            parameters=(_SCOPE,),
        )
        return None if row is None else self._from_row(row)

    async def save(self, *, limits: RuntimeRiskLimits) -> None:
        """Atomically replace current limits and append one audit event."""
        parameters = (
            limits.max_open_positions,
            format(limits.max_position_size_usdt, "f"),
            limits.updated_at.isoformat(),
            limits.updated_by,
        )
        async with self._database.transaction() as connection:
            await connection.execute(
                _UPSERT_SQL,
                (_SCOPE, *parameters),
            )
            await connection.execute(_INSERT_EVENT_SQL, parameters)

    @staticmethod
    def _from_row(row: Row) -> RuntimeRiskLimits:
        """Map one validated SQLite row into an immutable snapshot."""
        max_open_positions = row["max_open_positions"]
        max_position_size_usdt = row["max_position_size_usdt"]
        updated_at = row["updated_at"]
        updated_by = row["updated_by"]
        if isinstance(max_open_positions, bool) or not isinstance(
            max_open_positions, int
        ):
            raise TypeError("SQLite runtime maximum open positions must be integer")
        if not isinstance(max_position_size_usdt, str):
            raise TypeError("SQLite runtime maximum position size must be text")
        if not isinstance(updated_at, str) or not isinstance(updated_by, str):
            raise TypeError("SQLite runtime risk-limit audit values must be text")
        return RuntimeRiskLimits(
            max_open_positions=max_open_positions,
            max_position_size_usdt=Decimal(max_position_size_usdt),
            updated_at=datetime.fromisoformat(updated_at),
            updated_by=updated_by,
        )
