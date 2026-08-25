"""SQLite persistence for durable LIVE equity high-water marks."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from sqlite3 import Row
from typing import Final

from botragram.models import LiveEquityHighWaterMark
from botragram.repositories import LiveEquityHighWaterRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = ["SQLiteLiveEquityHighWaterRepository"]


_SELECT_SQL: Final[str] = """
SELECT asset, equity, observed_at
FROM live_equity_high_water_marks
WHERE asset = ?;
"""
_UPSERT_IF_GREATER_SQL: Final[str] = """
INSERT INTO live_equity_high_water_marks (asset, equity, observed_at)
VALUES (?, ?, ?)
ON CONFLICT (asset)
DO UPDATE SET
    equity = excluded.equity,
    observed_at = excluded.observed_at
WHERE CAST(excluded.equity AS REAL) > CAST(live_equity_high_water_marks.equity AS REAL);
"""
_ASSET_ERROR: Final[str] = "LIVE equity asset must not be empty"


class SQLiteLiveEquityHighWaterRepository(LiveEquityHighWaterRepository):
    """Store one monotonic high-water equity value per collateral asset."""

    __slots__ = ("_database",)

    def __init__(self, *, database: SQLiteDatabase) -> None:
        """Initialize the repository with an initialized SQLite database."""
        self._database = database

    async def get(self, *, asset: str) -> LiveEquityHighWaterMark | None:
        """Return the persisted high-water mark for an asset."""
        row = await self._database.fetch_one(
            statement=_SELECT_SQL,
            parameters=(self._normalize_asset(asset),),
        )
        if row is None:
            return None
        return self._from_row(row)

    async def save_if_greater(
        self,
        *,
        asset: str,
        equity: Decimal,
        observed_at: datetime,
    ) -> LiveEquityHighWaterMark:
        """Persist and return the maximum of the stored and observed equity."""
        normalized_asset = self._normalize_asset(asset)
        self._validate_equity(equity)
        observed_at_text = self._datetime_to_utc_text(observed_at)
        await self._database.execute(
            statement=_UPSERT_IF_GREATER_SQL,
            parameters=(normalized_asset, format(equity, "f"), observed_at_text),
        )
        high_water_mark = await self.get(asset=normalized_asset)
        if high_water_mark is None:
            raise RuntimeError("LIVE equity high-water mark was not persisted")
        return high_water_mark

    @staticmethod
    def _normalize_asset(asset: str) -> str:
        """Normalize and validate a collateral asset."""
        normalized_asset = asset.strip().upper()
        if not normalized_asset:
            raise ValueError(_ASSET_ERROR)
        return normalized_asset

    @staticmethod
    def _validate_equity(equity: Decimal) -> None:
        """Reject non-finite or non-positive account equity values."""
        if not equity.is_finite() or equity <= Decimal("0"):
            raise ValueError("LIVE equity must be finite and positive")

    @staticmethod
    def _datetime_to_utc_text(value: datetime) -> str:
        """Serialize a timezone-aware observation time in UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LIVE equity observation time must be timezone-aware")
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _from_row(row: Row) -> LiveEquityHighWaterMark:
        """Map one SQLite row into a high-water model."""
        asset = row["asset"]
        equity = row["equity"]
        observed_at = row["observed_at"]
        if not isinstance(asset, str) or not isinstance(equity, str):
            raise TypeError("SQLite LIVE equity high-water values must be text")
        if not isinstance(observed_at, str):
            raise TypeError("SQLite LIVE equity high-water timestamp must be text")
        parsed_observed_at = datetime.fromisoformat(observed_at)
        if parsed_observed_at.tzinfo is None:
            raise ValueError("SQLite LIVE equity timestamp must be timezone-aware")
        return LiveEquityHighWaterMark(
            asset=asset,
            equity=Decimal(equity),
            observed_at=parsed_observed_at,
        )
