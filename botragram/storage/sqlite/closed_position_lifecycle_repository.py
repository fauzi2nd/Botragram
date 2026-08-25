"""SQLite persistence for closed Botragram position lifecycles."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from sqlite3 import Row
from typing import Final

from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    PositionSide,
)
from botragram.models import ClosedPositionLifecycle, PendingClosedPositionLifecycle
from botragram.repositories import ClosedPositionLifecycleRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = ["SQLiteClosedPositionLifecycleRepository"]


_COLUMNS: Final[str] = """
entry_client_order_id, symbol, position_side, entry_order_id,
exit_client_order_id, exit_order_id, close_reason, provenance, recorded_at,
gross_realized_pnl, fee, fee_asset, net_pnl, closed_at
"""
_INSERT_STAGE_SQL: Final[str] = f"""
INSERT INTO closed_position_lifecycles ({_COLUMNS})
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
ON CONFLICT (entry_client_order_id) DO NOTHING;
"""
_COMPLETE_SQL: Final[str] = """
UPDATE closed_position_lifecycles
SET gross_realized_pnl = ?, fee = ?, fee_asset = ?, net_pnl = ?, closed_at = ?
WHERE entry_client_order_id = ?
  AND gross_realized_pnl IS NULL;
"""
_SELECT_BASE: Final[str] = f"SELECT {_COLUMNS} FROM closed_position_lifecycles"


class SQLiteClosedPositionLifecycleRepository(ClosedPositionLifecycleRepository):
    """Persist immutable closure ownership and completed performance facts."""

    __slots__ = ("_database",)

    def __init__(self, *, database: SQLiteDatabase) -> None:
        """Initialize the repository with one connected database."""
        self._database = database

    async def stage(self, *, lifecycle: PendingClosedPositionLifecycle) -> None:
        """Insert closure ownership once and verify idempotent replay."""
        await self._database.execute(
            statement=_INSERT_STAGE_SQL,
            parameters=self._stage_parameters(lifecycle),
        )
        existing = await self.get_by_entry_client_order_id(
            entry_client_order_id=lifecycle.entry_client_order_id,
        )
        ownership = (
            existing.ownership
            if isinstance(existing, ClosedPositionLifecycle)
            else existing
        )
        if ownership != lifecycle:
            raise RuntimeError("Closed lifecycle identity conflicts with storage")

    async def complete(self, *, lifecycle: ClosedPositionLifecycle) -> None:
        """Complete one staged lifecycle and verify immutable replay."""
        await self._database.execute(
            statement=_COMPLETE_SQL,
            parameters=(
                str(lifecycle.gross_realized_pnl),
                str(lifecycle.fee),
                lifecycle.fee_asset,
                str(lifecycle.net_pnl),
                self._datetime_text(lifecycle.closed_at),
                lifecycle.entry_client_order_id,
            ),
        )
        existing = await self.get_by_entry_client_order_id(
            entry_client_order_id=lifecycle.entry_client_order_id,
        )
        if existing != lifecycle:
            raise RuntimeError(
                "Completed lifecycle conflicts with authoritative storage"
            )

    async def get_pending(self) -> Sequence[PendingClosedPositionLifecycle]:
        """Return staged lifecycle records in recording order."""
        rows = await self._database.fetch_all(
            statement=(
                _SELECT_BASE
                + " WHERE gross_realized_pnl IS NULL ORDER BY recorded_at ASC;"
            )
        )
        return tuple(self._pending_from_row(row) for row in rows)

    async def get_completed(self) -> Sequence[ClosedPositionLifecycle]:
        """Return all completed lifecycles without a history truncation limit."""
        rows = await self._database.fetch_all(
            statement=(
                _SELECT_BASE
                + " WHERE gross_realized_pnl IS NOT NULL ORDER BY closed_at ASC;"
            )
        )
        return tuple(self._completed_from_row(row) for row in rows)

    async def get_by_entry_client_order_id(
        self,
        *,
        entry_client_order_id: str,
    ) -> ClosedPositionLifecycle | PendingClosedPositionLifecycle | None:
        """Return one lifecycle by canonical entry client identity."""
        normalized_identity = entry_client_order_id.strip()
        if not normalized_identity:
            raise ValueError("Entry client order ID must not be empty")
        row = await self._database.fetch_one(
            statement=_SELECT_BASE + " WHERE entry_client_order_id = ? LIMIT 1;",
            parameters=(normalized_identity,),
        )
        if row is None:
            return None
        if row["gross_realized_pnl"] is None:
            return self._pending_from_row(row)
        return self._completed_from_row(row)

    @classmethod
    def _completed_from_row(cls, row: Row) -> ClosedPositionLifecycle:
        """Map one financially completed SQLite row."""
        ownership = cls._pending_from_row(row)
        fee_asset = row["fee_asset"]
        if not isinstance(fee_asset, str):
            raise TypeError("Closed lifecycle fee asset must be text")
        return ClosedPositionLifecycle(
            ownership=ownership,
            gross_realized_pnl=cls._decimal(row, "gross_realized_pnl"),
            fee=cls._decimal(row, "fee"),
            fee_asset=fee_asset,
            net_pnl=cls._decimal(row, "net_pnl"),
            closed_at=cls._datetime(row, "closed_at"),
        )

    @classmethod
    def _pending_from_row(cls, row: Row) -> PendingClosedPositionLifecycle:
        """Map exact ownership fields from one SQLite row."""
        return PendingClosedPositionLifecycle(
            entry_client_order_id=cls._text(row, "entry_client_order_id"),
            symbol=cls._text(row, "symbol"),
            position_side=PositionSide(cls._text(row, "position_side")),
            entry_order_id=cls._text(row, "entry_order_id"),
            exit_client_order_id=cls._text(row, "exit_client_order_id"),
            exit_order_id=cls._text(row, "exit_order_id"),
            close_reason=ClosedPositionReason(cls._text(row, "close_reason")),
            provenance=ClosedPositionProvenance(cls._text(row, "provenance")),
            recorded_at=cls._datetime(row, "recorded_at"),
        )

    @classmethod
    def _stage_parameters(
        cls,
        lifecycle: PendingClosedPositionLifecycle,
    ) -> tuple[object, ...]:
        """Serialize exact immutable ownership fields."""
        return (
            lifecycle.entry_client_order_id,
            lifecycle.symbol,
            lifecycle.position_side.value,
            lifecycle.entry_order_id,
            lifecycle.exit_client_order_id,
            lifecycle.exit_order_id,
            lifecycle.close_reason.value,
            lifecycle.provenance.value,
            cls._datetime_text(lifecycle.recorded_at),
        )

    @staticmethod
    def _text(row: Row, column: str) -> str:
        """Return one required SQLite text value."""
        value = row[column]
        if not isinstance(value, str):
            raise TypeError(f"Closed lifecycle {column} must be text")
        return value

    @classmethod
    def _decimal(cls, row: Row, column: str) -> Decimal:
        """Return one required SQLite decimal text value."""
        return Decimal(cls._text(row, column))

    @classmethod
    def _datetime(cls, row: Row, column: str) -> datetime:
        """Return one required timezone-aware SQLite datetime."""
        value = datetime.fromisoformat(cls._text(row, column))
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"Closed lifecycle {column} must be timezone-aware")
        return value

    @staticmethod
    def _datetime_text(value: datetime) -> str:
        """Serialize one timezone-aware timestamp in UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Closed lifecycle timestamp must be timezone-aware")
        return value.astimezone(UTC).isoformat()
