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
import sqlite3
from datetime import UTC, datetime
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    ExchangeType,
    ExecutionPolicy,
    MarketType,
    StrategyType,
)
from botragram.repositories import RuntimeSettingsRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = ["SQLiteRuntimeSettingsRepository"]


# =============================================================================
# Constants
# =============================================================================
_STRATEGY_KEY: Final[str] = "active_strategy"
_LEVERAGE_KEY: Final[str] = "active_leverage"
_DYNAMIC_LEVERAGE_KEY: Final[str] = "dynamic_leverage_enabled"
_MARKET_TYPE_KEY: Final[str] = "active_market_type"
_EXCHANGE_KEY: Final[str] = "active_exchange"
_EXECUTION_POLICY_KEY: Final[str] = "active_execution_policy"
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

    async def _safe_fetch_value(self, key: str) -> str | None:
        """Fetch raw setting value, returning None if table does not exist."""
        try:
            row = await self._database.fetch_one(
                statement=_SELECT_SQL,
                parameters=(key,),
            )
            if row is None:
                return None
            raw_value = row["value"]
            if not isinstance(raw_value, str):
                raise TypeError("SQLite runtime setting value must be text")
            return raw_value
        except sqlite3.OperationalError:
            return None

    async def get_strategy(self) -> StrategyType | None:
        """Return the latest durable runtime strategy, if configured."""
        raw_value = await self._safe_fetch_value(_STRATEGY_KEY)
        if raw_value is None:
            return None
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
        raw_value = await self._safe_fetch_value(_LEVERAGE_KEY)
        if raw_value is None:
            return None
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

    async def get_dynamic_leverage(self) -> bool | None:
        """Return latest durable dynamic leverage setting, if configured."""
        raw_value = await self._safe_fetch_value(_DYNAMIC_LEVERAGE_KEY)
        if raw_value is None:
            return None
        norm = raw_value.strip().lower()
        if norm in ("1", "true", "yes", "on"):
            return True
        if norm in ("0", "false", "no", "off"):
            return False
        return None

    async def save_dynamic_leverage(self, *, enabled: bool) -> None:
        """Atomically persist dynamic leverage setting."""
        now = datetime.now(UTC).isoformat()
        val_str = "true" if enabled else "false"
        async with self._database.transaction() as connection:
            await connection.execute(
                _UPSERT_SQL,
                (_DYNAMIC_LEVERAGE_KEY, val_str, now),
            )

    async def get_market_type(self) -> MarketType | None:
        """Return the latest durable runtime market type, if configured."""
        raw_value = await self._safe_fetch_value(_MARKET_TYPE_KEY)
        if raw_value is None:
            return None
        try:
            return MarketType(raw_value)
        except ValueError:
            return None

    async def save_market_type(self, *, market_type: MarketType) -> None:
        """Atomically persist the active runtime market type."""
        now = datetime.now(UTC).isoformat()
        async with self._database.transaction() as connection:
            await connection.execute(
                _UPSERT_SQL,
                (_MARKET_TYPE_KEY, market_type.value, now),
            )

    async def get_exchange(self) -> ExchangeType | None:
        """Return the latest durable runtime exchange, if configured."""
        raw_value = await self._safe_fetch_value(_EXCHANGE_KEY)
        if raw_value is None:
            return None
        try:
            return ExchangeType(raw_value)
        except ValueError:
            return None

    async def save_exchange(self, *, exchange_type: ExchangeType) -> None:
        """Atomically persist the active runtime exchange."""
        now = datetime.now(UTC).isoformat()
        async with self._database.transaction() as connection:
            await connection.execute(
                _UPSERT_SQL,
                (_EXCHANGE_KEY, exchange_type.value, now),
            )

    async def get_execution_policy(self) -> ExecutionPolicy | None:
        """Return the latest durable runtime execution policy, if configured."""
        raw_value = await self._safe_fetch_value(_EXECUTION_POLICY_KEY)
        if raw_value is None:
            return None
        try:
            return ExecutionPolicy(raw_value)
        except ValueError:
            return None

    async def save_execution_policy(self, *, execution_policy: ExecutionPolicy) -> None:
        """Atomically persist the active runtime execution policy."""
        now = datetime.now(UTC).isoformat()
        async with self._database.transaction() as connection:
            await connection.execute(
                _UPSERT_SQL,
                (_EXECUTION_POLICY_KEY, execution_policy.value, now),
            )
