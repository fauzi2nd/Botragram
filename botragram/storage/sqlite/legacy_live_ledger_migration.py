"""
Botragram

Description:
    One-time safe import of a legacy TESTNET LIVE Botragram ledger.

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
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Row
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = [
    "SQLiteTestnetLegacyLiveLedgerMigration",
]


# =============================================================================
# Constants
# =============================================================================
_SCHEMA_VERSION_SQL: Final[str] = """
SELECT version
FROM schema_version
ORDER BY version DESC
LIMIT 1;
"""
_EXISTING_DURABLE_POSITION_SQL: Final[str] = """
SELECT 1
FROM positions
WHERE entry_client_order_id IS NOT NULL
LIMIT 1;
"""
_RECORD_COUNT_SQL_TEMPLATE: Final[str] = "SELECT COUNT(*) FROM {table_name};"
_POSITION_COLUMNS: Final[tuple[str, ...]] = (
    "symbol",
    "side",
    "quantity",
    "entry_price",
    "current_price",
    "unrealized_pnl",
    "leverage",
    "opened_at",
    "updated_at",
    "stop_loss",
    "take_profit",
    "interval",
    "strategy_type",
    "protection_step",
    "stop_loss_client_algo_id",
    "take_profit_client_algo_id",
    "entry_client_order_id",
    "pending_stop_loss",
    "pending_stop_loss_client_algo_id",
    "pending_protection_step",
)
_ORDER_COLUMNS: Final[tuple[str, ...]] = (
    "symbol",
    "order_id",
    "side",
    "order_type",
    "status",
    "quantity",
    "executed_quantity",
    "created_at",
    "updated_at",
    "price",
    "stop_price",
    "client_order_id",
)
_TRADE_COLUMNS: Final[tuple[str, ...]] = (
    "symbol",
    "trade_id",
    "order_id",
    "side",
    "price",
    "quantity",
    "quote_quantity",
    "fee",
    "fee_asset",
    "realized_pnl",
    "executed_at",
)
_SUBMISSION_ATTEMPT_COLUMNS: Final[tuple[str, ...]] = (
    "client_order_id",
    "symbol",
    "side",
    "order_type",
    "quantity",
    "signal_generated_at",
    "interval",
    "strategy_type",
    "status",
    "exchange_order_id",
    "created_at",
    "updated_at",
)
_OPPORTUNITY_CLAIM_COLUMNS: Final[tuple[str, ...]] = (
    "symbol",
    "interval",
    "strategy_name",
    "signal_generated_at",
)
_DURABLE_LEDGER_TABLE_NAMES: Final[tuple[str, ...]] = (
    "orders",
    "trades",
    "submission_attempts",
    "autonomous_live_opportunity_claims",
)


# =============================================================================
# Internal Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class _LedgerTable:
    """Describe one fixed Botragram LIVE ledger table."""

    name: str
    columns: tuple[str, ...]

    @property
    def select_statement(self) -> str:
        """Return a deterministic complete-row selection statement."""
        return f"SELECT {', '.join(self.columns)} FROM {self.name};"

    @property
    def insert_statement(self) -> str:
        """Return an idempotent complete-row import statement."""
        placeholders = ", ".join("?" for _ in self.columns)
        return (
            f"INSERT OR REPLACE INTO {self.name} "
            f"({', '.join(self.columns)}) VALUES ({placeholders});"
        )


_LEDGER_TABLES: Final[tuple[_LedgerTable, ...]] = (
    _LedgerTable(name="positions", columns=_POSITION_COLUMNS),
    _LedgerTable(name="orders", columns=_ORDER_COLUMNS),
    _LedgerTable(name="trades", columns=_TRADE_COLUMNS),
    _LedgerTable(name="submission_attempts", columns=_SUBMISSION_ATTEMPT_COLUMNS),
    _LedgerTable(
        name="autonomous_live_opportunity_claims",
        columns=_OPPORTUNITY_CLAIM_COLUMNS,
    ),
)


# =============================================================================
# Migration Classes
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class SQLiteTestnetLegacyLiveLedgerMigration:
    """Import a legacy Botragram TESTNET ledger only into an empty target.

    The source is opened read-only. A target that already contains durable
    Botragram records is never merged, which prevents an unrelated deployment
    from inheriting legacy state. The caller is responsible for restricting
    invocation to the intended TESTNET deployment.
    """

    target_database: SQLiteDatabase
    source_database_path: Path

    async def migrate_if_required(self) -> bool:
        """Copy compatible legacy ledger rows when the target has no ledger.

        Returns:
            Whether a legacy ledger was imported.

        Raises:
            RuntimeError: If the source and target schema versions differ.
        """
        source_path = self.source_database_path.resolve()
        target_path = self.target_database.database_path.resolve()
        if source_path == target_path or not source_path.is_file():
            return False

        source_database = SQLiteDatabase(
            database_path=source_path,
            read_only=True,
        )
        try:
            await source_database.connect()
            if await self._target_has_durable_ledger():
                return False
            await self._require_matching_schema(source_database=source_database)
            if not await self._source_has_durable_ledger(
                source_database=source_database,
            ):
                return False
            await self._copy_rows(source_database=source_database)
        finally:
            await source_database.close()

        return True

    async def _require_matching_schema(
        self,
        *,
        source_database: SQLiteDatabase,
    ) -> None:
        """Require the legacy source to have exactly the target schema version."""
        source_version = await self._get_schema_version(database=source_database)
        target_version = await self._get_schema_version(database=self.target_database)
        if source_version != target_version:
            raise RuntimeError(
                "Legacy TESTNET LIVE database schema does not match the target: "
                f"source={source_version} target={target_version}"
            )

    async def _target_has_durable_ledger(self) -> bool:
        """Return whether target state makes a legacy merge unsafe."""
        if await self._has_durable_position(database=self.target_database):
            return True
        return await self._has_records(
            database=self.target_database,
            table_names=_DURABLE_LEDGER_TABLE_NAMES,
        )

    async def _source_has_durable_ledger(
        self,
        *,
        source_database: SQLiteDatabase,
    ) -> bool:
        """Return whether the source contains proven Botragram LIVE evidence."""
        if await self._has_durable_position(database=source_database):
            return True
        return await self._has_records(
            database=source_database,
            table_names=("submission_attempts",),
        )

    async def _copy_rows(
        self,
        *,
        source_database: SQLiteDatabase,
    ) -> None:
        """Atomically import the fixed ledger subset from the read-only source."""
        rows_by_table: list[tuple[_LedgerTable, tuple[tuple[object, ...], ...]]] = []
        for table in _LEDGER_TABLES:
            source_rows = await source_database.fetch_all(
                statement=table.select_statement
            )
            rows_by_table.append(
                (
                    table,
                    tuple(self._to_values(row=row) for row in source_rows),
                )
            )

        async with self.target_database.transaction() as connection:
            for table, parameter_rows in rows_by_table:
                if parameter_rows:
                    await connection.executemany(table.insert_statement, parameter_rows)

    @staticmethod
    async def _get_schema_version(*, database: SQLiteDatabase) -> int:
        """Return the exact current schema version from one initialized database."""
        row = await database.fetch_one(statement=_SCHEMA_VERSION_SQL)
        if row is None:
            return 0
        return SQLiteTestnetLegacyLiveLedgerMigration._get_integer(
            row=row,
            column="version",
        )

    @staticmethod
    async def _has_durable_position(*, database: SQLiteDatabase) -> bool:
        """Return whether a position has a persisted Botragram entry identity."""
        row = await database.fetch_one(statement=_EXISTING_DURABLE_POSITION_SQL)
        return row is not None

    @staticmethod
    async def _has_records(
        *,
        database: SQLiteDatabase,
        table_names: tuple[str, ...],
    ) -> bool:
        """Return whether any fixed ledger table contains records."""
        for table_name in table_names:
            row = await database.fetch_one(
                statement=_RECORD_COUNT_SQL_TEMPLATE.format(table_name=table_name),
            )
            if row is None:
                raise RuntimeError(f"SQLite count query returned no row: {table_name}")
            if SQLiteTestnetLegacyLiveLedgerMigration._get_integer(
                row=row,
                column=0,
            ):
                return True
        return False

    @staticmethod
    def _to_values(*, row: Row) -> tuple[object, ...]:
        """Convert one SQLite row into a parameter tuple without coercion."""
        return tuple(row)

    @staticmethod
    def _get_integer(*, row: Row, column: str | int) -> int:
        """Return one non-boolean integer SQLite field."""
        value: object = row[column]
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"SQLite column {column!r} must contain an integer")
        return value
