"""
Botragram

Description:
    SQLite candle repository implementation.

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
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from sqlite3 import Row
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.models import Candle
from botragram.repositories import CandleRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = [
    "SQLiteCandleRepository",
]


# =============================================================================
# Constants
# =============================================================================
_CANDLE_LIMIT_ERROR: Final[str] = "Candle limit must be greater than zero"
_CANDLE_TIME_RANGE_ERROR: Final[str] = "Candle start time must not be after end time"
_SYMBOL_ERROR: Final[str] = "Trading symbol must not be empty"

_UPSERT_CANDLE_SQL: Final[str] = """
INSERT INTO candles (
    symbol,
    interval,
    open_time,
    close_time,
    open_price,
    high_price,
    low_price,
    close_price,
    volume
)
VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?
)
ON CONFLICT (
    symbol,
    interval,
    open_time
)
DO UPDATE SET
    close_time = excluded.close_time,
    open_price = excluded.open_price,
    high_price = excluded.high_price,
    low_price = excluded.low_price,
    close_price = excluded.close_price,
    volume = excluded.volume;
"""

_SELECT_LATEST_SQL: Final[str] = """
SELECT
    symbol,
    interval,
    open_time,
    close_time,
    open_price,
    high_price,
    low_price,
    close_price,
    volume
FROM candles
WHERE
    symbol = ?
    AND interval = ?
ORDER BY open_time DESC
LIMIT ?;
"""

_SELECT_BETWEEN_SQL: Final[str] = """
SELECT
    symbol,
    interval,
    open_time,
    close_time,
    open_price,
    high_price,
    low_price,
    close_price,
    volume
FROM candles
WHERE
    symbol = ?
    AND interval = ?
    AND open_time >= ?
    AND open_time <= ?
ORDER BY open_time ASC;
"""

_SELECT_BY_OPEN_TIME_SQL: Final[str] = """
SELECT
    symbol,
    interval,
    open_time,
    close_time,
    open_price,
    high_price,
    low_price,
    close_price,
    volume
FROM candles
WHERE
    symbol = ?
    AND interval = ?
    AND open_time = ?
LIMIT 1;
"""

_DELETE_BEFORE_SQL: Final[str] = """
DELETE FROM candles
WHERE open_time < ?;
"""

_DELETE_BEFORE_SYMBOL_SQL: Final[str] = """
DELETE FROM candles
WHERE
    open_time < ?
    AND symbol = ?;
"""

_DELETE_BEFORE_INTERVAL_SQL: Final[str] = """
DELETE FROM candles
WHERE
    open_time < ?
    AND interval = ?;
"""

_DELETE_BEFORE_SYMBOL_INTERVAL_SQL: Final[str] = """
DELETE FROM candles
WHERE
    open_time < ?
    AND symbol = ?
    AND interval = ?;
"""

_COUNT_ALL_SQL: Final[str] = """
SELECT COUNT(*) AS record_count
FROM candles;
"""

_COUNT_SYMBOL_SQL: Final[str] = """
SELECT COUNT(*) AS record_count
FROM candles
WHERE symbol = ?;
"""

_COUNT_INTERVAL_SQL: Final[str] = """
SELECT COUNT(*) AS record_count
FROM candles
WHERE interval = ?;
"""

_COUNT_SYMBOL_INTERVAL_SQL: Final[str] = """
SELECT COUNT(*) AS record_count
FROM candles
WHERE
    symbol = ?
    AND interval = ?;
"""

_RECORD_COUNT_COLUMN: Final[str] = "record_count"


# =============================================================================
# Type Aliases
# =============================================================================
type CandleParameters = tuple[
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
]


# =============================================================================
# Repository Implementations
# =============================================================================
class SQLiteCandleRepository(CandleRepository):
    """Persist candlestick market data in SQLite."""

    __slots__ = ("_database",)

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
    ) -> None:
        """Initialize the SQLite candle repository.

        Args:
            database: Connected SQLite database manager.
        """
        self._database = database

    async def save(
        self,
        *,
        candle: Candle,
    ) -> None:
        """Persist or replace a candlestick record."""
        await self._database.execute(
            statement=_UPSERT_CANDLE_SQL,
            parameters=self._to_parameters(candle),
        )

    async def save_many(
        self,
        *,
        candles: Sequence[Candle],
    ) -> None:
        """Persist or replace multiple candlestick records."""
        parameter_rows: tuple[CandleParameters, ...] = tuple(
            self._to_parameters(candle) for candle in candles
        )

        await self._database.execute_many(
            statement=_UPSERT_CANDLE_SQL,
            parameter_rows=parameter_rows,
        )

    async def get_latest(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
    ) -> Sequence[Candle]:
        """Return the latest candles for a symbol and interval."""
        if limit <= 0:
            raise ValueError(_CANDLE_LIMIT_ERROR)

        rows = await self._database.fetch_all(
            statement=_SELECT_LATEST_SQL,
            parameters=(
                self._normalize_symbol(symbol),
                interval.value,
                limit,
            ),
        )

        candles = tuple(self._from_row(row) for row in reversed(rows))

        return candles

    async def get_between(
        self,
        *,
        symbol: str,
        interval: Interval,
        start_time: datetime,
        end_time: datetime,
    ) -> Sequence[Candle]:
        """Return candles within an inclusive datetime range."""
        if start_time > end_time:
            raise ValueError(_CANDLE_TIME_RANGE_ERROR)

        rows = await self._database.fetch_all(
            statement=_SELECT_BETWEEN_SQL,
            parameters=(
                self._normalize_symbol(symbol),
                interval.value,
                self._datetime_to_text(start_time),
                self._datetime_to_text(end_time),
            ),
        )

        return tuple(self._from_row(row) for row in rows)

    async def get_by_open_time(
        self,
        *,
        symbol: str,
        interval: Interval,
        open_time: datetime,
    ) -> Candle | None:
        """Return a candle by symbol, interval, and open time."""
        row = await self._database.fetch_one(
            statement=_SELECT_BY_OPEN_TIME_SQL,
            parameters=(
                self._normalize_symbol(symbol),
                interval.value,
                self._datetime_to_text(open_time),
            ),
        )

        if row is None:
            return None

        return self._from_row(row)

    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
        interval: Interval | None = None,
    ) -> int:
        """Delete candles older than a datetime boundary."""
        statement, parameters = self._build_delete_query(
            before=before,
            symbol=symbol,
            interval=interval,
        )

        return await self._execute_delete(
            statement=statement,
            parameters=parameters,
        )

    async def count(
        self,
        *,
        symbol: str | None = None,
        interval: Interval | None = None,
    ) -> int:
        """Count stored candle records."""
        statement, parameters = self._build_count_query(
            symbol=symbol,
            interval=interval,
        )

        row = await self._database.fetch_one(
            statement=statement,
            parameters=parameters,
        )

        if row is None:
            return 0

        return self._get_integer(
            row,
            column=_RECORD_COUNT_COLUMN,
        )

    async def _execute_delete(
        self,
        *,
        statement: str,
        parameters: tuple[object, ...],
    ) -> int:
        """Execute a delete statement and return affected rows."""
        return await self._database.execute(
            statement=statement,
            parameters=parameters,
        )

    @classmethod
    def _to_parameters(
        cls,
        candle: Candle,
    ) -> CandleParameters:
        """Convert a candle into SQLite parameters."""
        return (
            cls._normalize_symbol(candle.symbol),
            candle.interval.value,
            cls._datetime_to_text(candle.open_time),
            cls._datetime_to_text(candle.close_time),
            cls._decimal_to_text(candle.open_price),
            cls._decimal_to_text(candle.high_price),
            cls._decimal_to_text(candle.low_price),
            cls._decimal_to_text(candle.close_price),
            cls._decimal_to_text(candle.volume),
        )

    @classmethod
    def _from_row(
        cls,
        row: Row,
    ) -> Candle:
        """Map a SQLite row into a Candle model."""
        return Candle(
            symbol=cls._get_string(
                row,
                column="symbol",
            ),
            interval=Interval(
                cls._get_string(
                    row,
                    column="interval",
                )
            ),
            open_time=cls._get_datetime(
                row,
                column="open_time",
            ),
            close_time=cls._get_datetime(
                row,
                column="close_time",
            ),
            open_price=cls._get_decimal(
                row,
                column="open_price",
            ),
            high_price=cls._get_decimal(
                row,
                column="high_price",
            ),
            low_price=cls._get_decimal(
                row,
                column="low_price",
            ),
            close_price=cls._get_decimal(
                row,
                column="close_price",
            ),
            volume=cls._get_decimal(
                row,
                column="volume",
            ),
        )

    @classmethod
    def _build_delete_query(
        cls,
        *,
        before: datetime,
        symbol: str | None,
        interval: Interval | None,
    ) -> tuple[str, tuple[object, ...]]:
        """Build a delete query from optional filters."""
        before_value = cls._datetime_to_text(before)

        if symbol is not None and interval is not None:
            return (
                _DELETE_BEFORE_SYMBOL_INTERVAL_SQL,
                (
                    before_value,
                    cls._normalize_symbol(symbol),
                    interval.value,
                ),
            )

        if symbol is not None:
            return (
                _DELETE_BEFORE_SYMBOL_SQL,
                (
                    before_value,
                    cls._normalize_symbol(symbol),
                ),
            )

        if interval is not None:
            return (
                _DELETE_BEFORE_INTERVAL_SQL,
                (
                    before_value,
                    interval.value,
                ),
            )

        return (
            _DELETE_BEFORE_SQL,
            (before_value,),
        )

    @classmethod
    def _build_count_query(
        cls,
        *,
        symbol: str | None,
        interval: Interval | None,
    ) -> tuple[str, tuple[object, ...]]:
        """Build a count query from optional filters."""
        if symbol is not None and interval is not None:
            return (
                _COUNT_SYMBOL_INTERVAL_SQL,
                (
                    cls._normalize_symbol(symbol),
                    interval.value,
                ),
            )

        if symbol is not None:
            return (
                _COUNT_SYMBOL_SQL,
                (cls._normalize_symbol(symbol),),
            )

        if interval is not None:
            return (
                _COUNT_INTERVAL_SQL,
                (interval.value,),
            )

        return (
            _COUNT_ALL_SQL,
            (),
        )

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError(_SYMBOL_ERROR)

        return normalized_symbol

    @staticmethod
    def _datetime_to_text(
        value: datetime,
    ) -> str:
        """Convert a datetime into ISO-8601 text."""
        if value.tzinfo is None:
            raise ValueError("SQLite candle datetime must be timezone-aware")

        return value.isoformat()

    @staticmethod
    def _decimal_to_text(
        value: Decimal,
    ) -> str:
        """Convert a Decimal into exact non-exponent text."""
        return format(value, "f")

    @classmethod
    def _get_datetime(
        cls,
        row: Row,
        *,
        column: str,
    ) -> datetime:
        """Return a datetime value from a SQLite row."""
        value = cls._get_string(
            row,
            column=column,
        )

        result = datetime.fromisoformat(value)

        if result.tzinfo is None:
            raise ValueError(
                f"SQLite column {column!r} must contain a timezone-aware datetime"
            )

        return result

    @classmethod
    def _get_decimal(
        cls,
        row: Row,
        *,
        column: str,
    ) -> Decimal:
        """Return a Decimal value from a SQLite row."""
        return Decimal(
            cls._get_string(
                row,
                column=column,
            )
        )

    @staticmethod
    def _get_string(
        row: Row,
        *,
        column: str,
    ) -> str:
        """Return a string column from a SQLite row."""
        value: object = row[column]

        if not isinstance(value, str):
            raise TypeError(f"SQLite column {column!r} must contain text")

        return value

    @staticmethod
    def _get_integer(
        row: Row,
        *,
        column: str,
    ) -> int:
        """Return an integer column from a SQLite row."""
        value: object = row[column]

        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"SQLite column {column!r} must contain an integer")

        return value
