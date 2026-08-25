"""
Botragram

Description:
    SQLite schema migration management.

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
from sqlite3 import Row
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = [
    "SQLiteMigrationManager",
]


# =============================================================================
# Constants
# =============================================================================
_SCHEMA_VERSION_TABLE: Final[str] = "schema_version"

_CREATE_SCHEMA_VERSION_TABLE_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_GET_SCHEMA_VERSION_SQL: Final[str] = """
SELECT version
FROM schema_version
ORDER BY version DESC
LIMIT 1;
"""

_INSERT_SCHEMA_VERSION_SQL: Final[str] = """
INSERT INTO schema_version (
    version
)
VALUES (?);
"""

_SCHEMA_VERSION_COLUMN: Final[str] = "version"

_INVALID_SCHEMA_VERSION_ERROR: Final[str] = "SQLite schema version must not be negative"

_NEWER_SCHEMA_ERROR_TEMPLATE: Final[str] = (
    "SQLite database schema version {database_version} is newer than "
    "supported application version {application_version}"
)

_UNSUPPORTED_TARGET_VERSION_ERROR_TEMPLATE: Final[str] = (
    "Unsupported SQLite target schema version {target_version}"
)

_NEWER_THAN_TARGET_ERROR_TEMPLATE: Final[str] = (
    "SQLite database schema version {database_version} is newer than "
    "requested target version {target_version}"
)


# =============================================================================
# Migration Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class _Migration:
    """Immutable SQLite schema migration."""

    version: int
    script: str

    def __post_init__(self) -> None:
        """Validate migration metadata."""
        if self.version <= 0:
            raise ValueError("Migration version must be greater than zero")

        if not self.script.strip():
            raise ValueError("Migration script must not be empty")


# =============================================================================
# Migrations
# =============================================================================
_MIGRATIONS: Final[tuple[_Migration, ...]] = (
    _Migration(
        version=1,
        script="""
        CREATE TABLE IF NOT EXISTS candles (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,

            open_time TEXT NOT NULL,
            close_time TEXT NOT NULL,

            open_price TEXT NOT NULL,
            high_price TEXT NOT NULL,
            low_price TEXT NOT NULL,
            close_price TEXT NOT NULL,

            volume TEXT NOT NULL,

            PRIMARY KEY (
                symbol,
                interval,
                open_time
            )
        );

        CREATE INDEX IF NOT EXISTS idx_candles_lookup
        ON candles (
            symbol,
            interval,
            open_time
        );
        """,
    ),
    _Migration(
        version=2,
        script="""
        CREATE TABLE IF NOT EXISTS signals (
            symbol TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            generated_at TEXT NOT NULL,

            signal_type TEXT NOT NULL,
            price TEXT NOT NULL,
            confidence TEXT NOT NULL,
            reason TEXT,

            PRIMARY KEY (
                symbol,
                strategy_name,
                generated_at
            )
        );

        CREATE INDEX IF NOT EXISTS idx_signals_generated_at
        ON signals (
            generated_at
        );

        CREATE INDEX IF NOT EXISTS idx_signals_lookup
        ON signals (
            symbol,
            strategy_name,
            signal_type,
            generated_at
        );
        """,
    ),
    _Migration(
        version=3,
        script="""
    CREATE TABLE IF NOT EXISTS orders (
        symbol TEXT NOT NULL,
        order_id TEXT NOT NULL,

        side TEXT NOT NULL,
        order_type TEXT NOT NULL,
        status TEXT NOT NULL,

        quantity TEXT NOT NULL,
        executed_quantity TEXT NOT NULL,

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        price TEXT,
        stop_price TEXT,

        PRIMARY KEY (
            symbol,
            order_id
        )
    );

    CREATE INDEX IF NOT EXISTS idx_orders_created_at
    ON orders (
        created_at
    );

    CREATE INDEX IF NOT EXISTS idx_orders_lookup
    ON orders (
        symbol,
        status,
        side,
        order_type,
        created_at
    );
    """,
    ),
    _Migration(
        version=4,
        script="""
    CREATE TABLE IF NOT EXISTS trades (
        symbol TEXT NOT NULL,
        trade_id TEXT NOT NULL,

        order_id TEXT NOT NULL,

        side TEXT NOT NULL,

        price TEXT NOT NULL,
        quantity TEXT NOT NULL,
        quote_quantity TEXT NOT NULL,

        fee TEXT NOT NULL,
        fee_asset TEXT NOT NULL,

        realized_pnl TEXT,

        executed_at TEXT NOT NULL,

        PRIMARY KEY (
            symbol,
            trade_id
        )
    );

    CREATE INDEX IF NOT EXISTS idx_trades_order
    ON trades (
        order_id
    );

    CREATE INDEX IF NOT EXISTS idx_trades_time
    ON trades (
        executed_at
    );

    CREATE INDEX IF NOT EXISTS idx_trades_lookup
    ON trades (
        symbol,
        side,
        executed_at
    );
    """,
    ),
    _Migration(
        version=5,
        script="""
    CREATE TABLE IF NOT EXISTS positions (
        symbol TEXT NOT NULL,

        side TEXT NOT NULL,

        quantity TEXT NOT NULL,
        entry_price TEXT NOT NULL,
        current_price TEXT NOT NULL,

        unrealized_pnl TEXT NOT NULL,
        leverage INTEGER NOT NULL,

        opened_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        PRIMARY KEY (
            symbol
        )
    );

    CREATE INDEX IF NOT EXISTS idx_positions_side
    ON positions (
        side
    );

    CREATE INDEX IF NOT EXISTS idx_positions_updated_at
    ON positions (
        updated_at
    );
    """,
    ),
    _Migration(
        version=6,
        script="""
        ALTER TABLE positions
        ADD COLUMN stop_loss TEXT;

        ALTER TABLE positions
        ADD COLUMN take_profit TEXT;
        """,
    ),
    _Migration(
        version=7,
        script="""
        ALTER TABLE positions
        ADD COLUMN interval TEXT;

        ALTER TABLE positions
        ADD COLUMN strategy_type TEXT;
        """,
    ),
    _Migration(
        version=8,
        script="""
        ALTER TABLE positions
        ADD COLUMN protection_step INTEGER NOT NULL DEFAULT 0;
        """,
    ),
    _Migration(
        version=9,
        script="""
        ALTER TABLE orders ADD COLUMN client_order_id TEXT;
        CREATE INDEX IF NOT EXISTS idx_orders_client_order_id
        ON orders (client_order_id);
        CREATE TABLE IF NOT EXISTS submission_attempts (
            client_order_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
            order_type TEXT NOT NULL, quantity TEXT NOT NULL,
            signal_generated_at TEXT NOT NULL, interval TEXT NOT NULL,
            strategy_type TEXT, status TEXT NOT NULL, exchange_order_id TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_submission_attempts_unresolved
        ON submission_attempts (status, created_at);
        """,
    ),
    _Migration(
        version=10,
        script="""
        ALTER TABLE positions
        ADD COLUMN stop_loss_client_algo_id TEXT;

        ALTER TABLE positions
        ADD COLUMN take_profit_client_algo_id TEXT;
        """,
    ),
    _Migration(
        version=11,
        script="""
        ALTER TABLE positions
        ADD COLUMN entry_client_order_id TEXT;
        """,
    ),
    _Migration(
        version=12,
        script="""
        CREATE TABLE IF NOT EXISTS autonomous_live_opportunity_claims (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            signal_generated_at TEXT NOT NULL,

            PRIMARY KEY (
                symbol,
                interval,
                strategy_name,
                signal_generated_at
            )
        );

        CREATE INDEX IF NOT EXISTS idx_autonomous_live_opportunity_claims_time
        ON autonomous_live_opportunity_claims (
            signal_generated_at
        );
        """,
    ),
    _Migration(
        version=13,
        script="""
        ALTER TABLE positions
        ADD COLUMN pending_stop_loss TEXT;

        ALTER TABLE positions
        ADD COLUMN pending_stop_loss_client_algo_id TEXT;

        ALTER TABLE positions
        ADD COLUMN pending_protection_step INTEGER NOT NULL DEFAULT 0;
        """,
    ),
    _Migration(
        version=14,
        script="""
        CREATE TABLE IF NOT EXISTS live_equity_high_water_marks (
            asset TEXT PRIMARY KEY,
            equity TEXT NOT NULL,
            observed_at TEXT NOT NULL
        );
        """,
    ),
)


# =============================================================================
# Migration Manager
# =============================================================================
class SQLiteMigrationManager:
    """Initialize and migrate the Botragram SQLite schema."""

    __slots__ = ("_database",)

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
    ) -> None:
        """Initialize the migration manager.

        Args:
            database: Connected SQLite database manager.
        """
        self._database = database

    @property
    def latest_version(self) -> int:
        """Return the latest schema version supported by the application."""
        if not _MIGRATIONS:
            return 0

        return _MIGRATIONS[-1].version

    async def initialize(
        self,
        *,
        target_version: int | None = None,
    ) -> int:
        """Create metadata tables and apply pending migrations.

        Args:
            target_version: Optional schema version to stop at. When omitted,
                every supported migration is applied.

        Returns:
            Final active schema version.

        Raises:
            ValueError: If ``target_version`` is not a defined migration.
            RuntimeError: If the database schema is newer than supported or
                newer than the requested target.
        """
        await self._database.execute_script(
            script=_CREATE_SCHEMA_VERSION_TABLE_SQL,
        )

        current_version = await self.get_current_version()
        requested_version = self._resolve_target_version(
            target_version=target_version,
        )

        if current_version > self.latest_version:
            raise RuntimeError(
                _NEWER_SCHEMA_ERROR_TEMPLATE.format(
                    database_version=current_version,
                    application_version=self.latest_version,
                )
            )

        if current_version > requested_version:
            raise RuntimeError(
                _NEWER_THAN_TARGET_ERROR_TEMPLATE.format(
                    database_version=current_version,
                    target_version=requested_version,
                )
            )

        for migration in _MIGRATIONS:
            if migration.version <= current_version:
                continue

            if migration.version > requested_version:
                break

            await self._apply_migration(
                migration=migration,
            )
            current_version = migration.version

        return current_version

    def _resolve_target_version(
        self,
        *,
        target_version: int | None,
    ) -> int:
        """Return the schema version this initialize call should reach."""
        if target_version is None:
            return self.latest_version

        known_versions = {migration.version for migration in _MIGRATIONS}

        if target_version not in known_versions:
            raise ValueError(
                _UNSUPPORTED_TARGET_VERSION_ERROR_TEMPLATE.format(
                    target_version=target_version,
                )
            )

        return target_version

    async def get_current_version(self) -> int:
        """Return the currently applied database schema version."""
        row = await self._database.fetch_one(
            statement=_GET_SCHEMA_VERSION_SQL,
        )

        if row is None:
            return 0

        version = self._get_integer(
            row,
            column=_SCHEMA_VERSION_COLUMN,
        )

        if version < 0:
            raise RuntimeError(_INVALID_SCHEMA_VERSION_ERROR)

        return version

    async def _apply_migration(
        self,
        *,
        migration: _Migration,
    ) -> None:
        """Apply one schema migration transactionally."""
        async with self._database.transaction() as connection:
            await connection.executescript(migration.script)
            await connection.execute(
                _INSERT_SCHEMA_VERSION_SQL,
                (migration.version,),
            )

    @staticmethod
    def _get_integer(
        row: Row,
        *,
        column: str,
    ) -> int:
        """Return an integer column from a SQLite row."""
        value: object = row[column]

        if isinstance(value, bool):
            raise TypeError(f"SQLite column {column!r} must contain an integer")

        if not isinstance(value, int):
            raise TypeError(f"SQLite column {column!r} must contain an integer")

        return value
