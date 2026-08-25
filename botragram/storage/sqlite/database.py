"""
Botragram

Description:
    Asynchronous SQLite database connection manager.

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
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from sqlite3 import Row

# =============================================================================
# Third-Party Imports
# =============================================================================
import aiosqlite

__all__ = [
    "SQLiteDatabase",
]


# =============================================================================
# Constants
# =============================================================================
_DEFAULT_BUSY_TIMEOUT_MS = 5_000

_DATABASE_PATH_ERROR = "SQLite database path must not be empty"
_BUSY_TIMEOUT_ERROR = "SQLite busy timeout must be greater than zero"
_CONNECTION_ERROR = "SQLite database is not connected"

_ENABLE_FOREIGN_KEYS_SQL = "PRAGMA foreign_keys = ON"
_ENABLE_WAL_SQL = "PRAGMA journal_mode = WAL"
_BUSY_TIMEOUT_SQL_TEMPLATE = "PRAGMA busy_timeout = {timeout_ms}"


# =============================================================================
# Database Classes
# =============================================================================
class SQLiteDatabase:
    """Manage one asynchronous SQLite database connection."""

    __slots__ = (
        "_busy_timeout_ms",
        "_connection",
        "_connection_lock",
        "_database_path",
        "_read_only",
    )

    def __init__(
        self,
        *,
        database_path: str | Path,
        busy_timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS,
        read_only: bool = False,
    ) -> None:
        """Initialize the SQLite database manager.

        Args:
            database_path: SQLite database file path.
            busy_timeout_ms: Time SQLite waits for a locked database.
            read_only: Whether the connection must reject database writes.

        Raises:
            ValueError: If configuration values are invalid.
        """
        normalized_path = str(database_path).strip()

        if not normalized_path:
            raise ValueError(_DATABASE_PATH_ERROR)

        if busy_timeout_ms <= 0:
            raise ValueError(_BUSY_TIMEOUT_ERROR)

        self._database_path = Path(normalized_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._read_only = read_only
        self._connection: aiosqlite.Connection | None = None
        self._connection_lock = asyncio.Lock()

    @property
    def database_path(self) -> Path:
        """Return the configured SQLite database path."""
        return self._database_path

    @property
    def is_connected(self) -> bool:
        """Return whether a database connection is available."""
        return self._connection is not None

    async def connect(self) -> None:
        """Open and configure the SQLite connection."""
        async with self._connection_lock:
            if self._connection is not None:
                return

            if not self._read_only:
                self._create_parent_directory()

            connection = await aiosqlite.connect(
                self._get_connection_target(),
                uri=self._read_only,
            )
            connection.row_factory = Row

            try:
                await connection.execute(
                    _ENABLE_FOREIGN_KEYS_SQL,
                )
                if not self._read_only:
                    await connection.execute(
                        _ENABLE_WAL_SQL,
                    )
                await connection.execute(
                    _BUSY_TIMEOUT_SQL_TEMPLATE.format(
                        timeout_ms=self._busy_timeout_ms,
                    )
                )
                await connection.commit()
            except BaseException:
                await connection.close()
                raise

            self._connection = connection

    async def close(self) -> None:
        """Close the active SQLite connection."""
        async with self._connection_lock:
            connection = self._connection

            if connection is None:
                return

            await connection.close()
            self._connection = None

    async def execute(
        self,
        *,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> int:
        """Execute one write statement and commit it.

        Args:
            statement: SQL statement.
            parameters: Positional SQL parameters.

        Returns:
            Number of affected rows.
        """
        self._validate_statement(statement)

        connection = self._require_connection()

        try:
            cursor = await connection.execute(
                statement,
                parameters,
            )
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise

        affected_rows = cursor.rowcount
        await cursor.close()

        return max(affected_rows, 0)

    async def execute_many(
        self,
        *,
        statement: str,
        parameter_rows: tuple[tuple[object, ...], ...],
    ) -> None:
        """Execute one statement for multiple parameter rows.

        Args:
            statement: SQL statement.
            parameter_rows: Positional parameter collections.
        """
        self._validate_statement(statement)

        if not parameter_rows:
            return

        connection = self._require_connection()

        try:
            await connection.executemany(
                statement,
                parameter_rows,
            )
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise

    async def execute_script(
        self,
        *,
        script: str,
    ) -> None:
        """Execute a SQL script and commit it.

        Args:
            script: SQL script containing one or more statements.
        """
        self._validate_statement(script)

        connection = self._require_connection()

        try:
            await connection.executescript(script)
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise

    async def fetch_one(
        self,
        *,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> Row | None:
        """Execute a query and return its first row.

        Args:
            statement: SQL query.
            parameters: Positional SQL parameters.

        Returns:
            First matching row, or None.
        """
        self._validate_statement(statement)

        connection = self._require_connection()

        async with connection.execute(
            statement,
            parameters,
        ) as cursor:
            row = await cursor.fetchone()

        return row

    async def fetch_all(
        self,
        *,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> tuple[Row, ...]:
        """Execute a query and return all rows.

        Args:
            statement: SQL query.
            parameters: Positional SQL parameters.

        Returns:
            Matching rows.
        """
        self._validate_statement(statement)

        connection = self._require_connection()

        async with connection.execute(
            statement,
            parameters,
        ) as cursor:
            rows = await cursor.fetchall()

        return tuple(rows)

    @asynccontextmanager
    async def transaction(
        self,
    ) -> AsyncGenerator[aiosqlite.Connection]:
        """Provide a transaction-scoped database connection.

        Yields:
            Active connection.

        The transaction is committed when the context exits normally and
        rolled back when an exception occurs.
        """
        connection = self._require_connection()

        try:
            await connection.execute("BEGIN")
            yield connection
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise

    def _require_connection(self) -> aiosqlite.Connection:
        """Return the active connection or raise RuntimeError."""
        connection = self._connection

        if connection is None:
            raise RuntimeError(_CONNECTION_ERROR)

        return connection

    def _create_parent_directory(self) -> None:
        """Create the parent directory for a file-backed database."""
        if self._database_path == Path(":memory:"):
            return

        parent = self._database_path.parent

        if parent != Path("."):
            parent.mkdir(
                parents=True,
                exist_ok=True,
            )

    def _get_connection_target(self) -> str | Path:
        """Return a SQLite target that preserves the configured access mode."""
        if not self._read_only:
            return self._database_path

        return f"{self._database_path.resolve().as_uri()}?mode=ro"

    @staticmethod
    def _validate_statement(
        statement: str,
    ) -> None:
        """Validate a SQL statement or script."""
        if not statement.strip():
            raise ValueError("SQL statement must not be empty")

    async def __aenter__(self) -> SQLiteDatabase:
        """Open the connection for an async context."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        """Close the connection after an async context."""
        del exc_type, exc_value, traceback
        await self.close()
