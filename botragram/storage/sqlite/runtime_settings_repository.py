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
