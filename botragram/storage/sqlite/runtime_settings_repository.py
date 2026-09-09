"""
Botragram

Description:
    SQLite persistence for durable runtime settings.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import StrategyType
from botragram.repositories import RuntimeSettingsRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = ["SQLiteRuntimeSettingsRepository"]


# =============================================================================
# Constants
# =============================================================================
_STRATEGY_KEY: Final[str] = "active_strategy"
_LEVERAGE_KEY: Final[str] = "active_leverage"
_TRAILING_STOP_ENABLED_KEY: Final[str] = "trailing_stop_enabled"
_TRAILING_STOP_TRIGGER_PCT_KEY: Final[str] = "trailing_stop_trigger_pct"
_TRAILING_STOP_DISTANCE_PCT_KEY: Final[str] = "trailing_stop_distance_pct"
_SELECT_SQL: Final[str] = """
SELECT value
FROM runtime_settings
WHERE key = ?;
"""
_UPSERT_SQL: Final[str] = """
INSERT INTO runtime_settings (key, value, updated_at)
VALUES (?, ?, ?)
ON CONFLICT (key) DO UPDATE SET
    value = excluded.value,
    updated_at = excluded.updated_at;
"""


# =============================================================================
# Repository Implementation
# =============================================================================
class SQLiteRuntimeSettingsRepository(RuntimeSettingsRepository):
    """Store and retrieve durable runtime settings from SQLite."""

    __slots__ = ("_database",)

    def __init__(self, *, database: SQLiteDatabase) -> None:
        """Initialize the repository with a connected database."""
        self._database = database

    async def get_strategy(self) -> StrategyType | None:
        """Return the latest durable runtime strategy, if configured."""
        row = await self._database.fetch_one(
            statement=_SELECT_SQL,
            parameters=(_STRATEGY_KEY,),
        )
        if row is None:
            return None
        raw_value = row["value"]
        if not isinstance(raw_value, str):
            raise TypeError("SQLite runtime setting value must be text")
        try:
            return StrategyType(raw_value)
        except ValueError:
            return None

    async def save_strategy(self, *, strategy_type: StrategyType) -> None:
        """Atomically persist the active runtime strategy."""
        now = datetime.now(UTC).isoformat()
        async with self._database.transaction() as connection:
            await connection.execute(
                _UPSERT_SQL,
                (_STRATEGY_KEY, strategy_type.value, now),
            )

    async def get_leverage(self) -> int | None:
        """Return the latest durable runtime leverage, if configured."""
        row = await self._database.fetch_one(
            statement=_SELECT_SQL,
            parameters=(_LEVERAGE_KEY,),
        )
        if row is None:
            return None
        raw_value = row["value"]
        if not isinstance(raw_value, str):
            raise TypeError("SQLite runtime setting value must be text")
        try:
            val = int(raw_value)
            return val if val > 0 else None
        except ValueError:
            return None

    async def save_leverage(self, *, leverage: int) -> None:
        """Atomically persist the active runtime leverage."""
        if isinstance(leverage, bool) or leverage <= 0:
            raise ValueError("Runtime leverage must be a positive integer")
        now = datetime.now(UTC).isoformat()
        async with self._database.transaction() as connection:
            await connection.execute(
                _UPSERT_SQL,
                (_LEVERAGE_KEY, str(leverage), now),
            )

    async def get_trailing_stop(self) -> tuple[bool, Decimal, Decimal] | None:
        """Return durable trailing stop settings (enabled, trigger, distance)."""
        row_enabled = await self._database.fetch_one(
            statement=_SELECT_SQL,
            parameters=(_TRAILING_STOP_ENABLED_KEY,),
        )
        row_trigger = await self._database.fetch_one(
            statement=_SELECT_SQL,
            parameters=(_TRAILING_STOP_TRIGGER_PCT_KEY,),
        )
        row_dist = await self._database.fetch_one(
            statement=_SELECT_SQL,
            parameters=(_TRAILING_STOP_DISTANCE_PCT_KEY,),
        )
        if row_enabled is None or row_trigger is None or row_dist is None:
            return None

        val_enabled_str = row_enabled["value"]
        val_trigger_str = row_trigger["value"]
        val_dist_str = row_dist["value"]
        if (
            not isinstance(val_enabled_str, str)
            or not isinstance(val_trigger_str, str)
            or not isinstance(val_dist_str, str)
        ):
            raise TypeError("SQLite runtime setting value must be text")

        try:
            enabled = val_enabled_str.strip().lower() in {"true", "1", "yes"}
            trigger_pct = Decimal(val_trigger_str)
            distance_pct = Decimal(val_dist_str)
            if not (Decimal("0") < trigger_pct < Decimal("1")):
                return None
            if not (Decimal("0") < distance_pct < Decimal("1")):
                return None
            if distance_pct >= trigger_pct:
                return None
            return (enabled, trigger_pct, distance_pct)
        except ValueError, InvalidOperation:
            return None

    async def save_trailing_stop(
        self,
        *,
        enabled: bool,
        trigger_pct: Decimal,
        distance_pct: Decimal,
    ) -> None:
        """Atomically persist trailing stop settings."""
        if not (Decimal("0") < trigger_pct < Decimal("1")):
            raise ValueError("Trailing stop trigger must be between 0 and 1 exclusive")
        if not (Decimal("0") < distance_pct < Decimal("1")):
            raise ValueError("Trailing stop distance must be between 0 and 1 exclusive")
        if distance_pct >= trigger_pct:
            raise ValueError(
                "Trailing stop distance must be strictly less than trigger"
            )

        now = datetime.now(UTC).isoformat()
        async with self._database.transaction() as connection:
            await connection.execute(
                _UPSERT_SQL,
                (_TRAILING_STOP_ENABLED_KEY, "true" if enabled else "false", now),
            )
            await connection.execute(
                _UPSERT_SQL,
                (_TRAILING_STOP_TRIGGER_PCT_KEY, str(trigger_pct), now),
            )
            await connection.execute(
                _UPSERT_SQL,
                (_TRAILING_STOP_DISTANCE_PCT_KEY, str(distance_pct), now),
            )
