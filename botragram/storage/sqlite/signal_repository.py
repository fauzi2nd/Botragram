"""
Botragram

Description:
    SQLite trading signal repository implementation.

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
from botragram.enums import SignalType
from botragram.models import Signal
from botragram.repositories import SignalRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = [
    "SQLiteSignalRepository",
]


# =============================================================================
# Constants
# =============================================================================
_SIGNAL_LIMIT_ERROR: Final[str] = "Signal limit must be greater than zero"
_SIGNAL_TIME_RANGE_ERROR: Final[str] = "Signal start time must not be after end time"
_SYMBOL_ERROR: Final[str] = "Trading symbol must not be empty"
_STRATEGY_NAME_ERROR: Final[str] = "Strategy name must not be empty"
_DATETIME_ERROR_TEMPLATE: Final[str] = "SQLite signal {label} must be timezone-aware"
_RECORD_COUNT_COLUMN: Final[str] = "record_count"

_UPSERT_SIGNAL_SQL: Final[str] = """
INSERT INTO signals (
    symbol,
    strategy_name,
    generated_at,
    signal_type,
    price,
    confidence,
    reason
)
VALUES (
    ?, ?, ?, ?, ?, ?, ?
)
ON CONFLICT (
    symbol,
    strategy_name,
    generated_at
)
DO UPDATE SET
    signal_type = excluded.signal_type,
    price = excluded.price,
    confidence = excluded.confidence,
    reason = excluded.reason;
"""

_SELECT_LATEST_BASE_SQL: Final[str] = """
SELECT
    symbol,
    strategy_name,
    generated_at,
    signal_type,
    price,
    confidence,
    reason
FROM signals
"""

_SELECT_BETWEEN_BASE_SQL: Final[str] = """
SELECT
    symbol,
    strategy_name,
    generated_at,
    signal_type,
    price,
    confidence,
    reason
FROM signals
"""

_SELECT_LATEST_FOR_SYMBOL_SQL: Final[str] = """
SELECT
    symbol,
    strategy_name,
    generated_at,
    signal_type,
    price,
    confidence,
    reason
FROM signals
WHERE
    symbol = ?
ORDER BY generated_at DESC
LIMIT 1;
"""

_SELECT_LATEST_FOR_SYMBOL_STRATEGY_SQL: Final[str] = """
SELECT
    symbol,
    strategy_name,
    generated_at,
    signal_type,
    price,
    confidence,
    reason
FROM signals
WHERE
    symbol = ?
    AND strategy_name = ?
ORDER BY generated_at DESC
LIMIT 1;
"""

_DELETE_BEFORE_SQL: Final[str] = """
DELETE FROM signals
WHERE generated_at < ?;
"""

_DELETE_BEFORE_SYMBOL_SQL: Final[str] = """
DELETE FROM signals
WHERE
    generated_at < ?
    AND symbol = ?;
"""

_COUNT_BASE_SQL: Final[str] = """
SELECT COUNT(*) AS record_count
FROM signals
"""


# =============================================================================
# Type Aliases
# =============================================================================
type SignalParameters = tuple[
    str,
    str,
    str,
    str,
    str,
    str,
    str | None,
]

type QueryParameters = tuple[object, ...]


# =============================================================================
# Repository Implementations
# =============================================================================
class SQLiteSignalRepository(SignalRepository):
    """Persist generated trading signals in SQLite."""

    __slots__ = ("_database",)

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
    ) -> None:
        """Initialize the SQLite signal repository.

        Args:
            database: Connected SQLite database manager.
        """
        self._database = database

    async def save(
        self,
        *,
        signal: Signal,
    ) -> None:
        """Persist or replace a trading signal."""
        await self._database.execute(
            statement=_UPSERT_SIGNAL_SQL,
            parameters=self._to_parameters(signal),
        )

    async def save_many(
        self,
        *,
        signals: Sequence[Signal],
    ) -> None:
        """Persist or replace multiple trading signals."""
        parameter_rows: tuple[SignalParameters, ...] = tuple(
            self._to_parameters(signal) for signal in signals
        )

        await self._database.execute_many(
            statement=_UPSERT_SIGNAL_SQL,
            parameter_rows=parameter_rows,
        )

    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> Sequence[Signal]:
        """Return the latest generated signals."""
        if limit <= 0:
            raise ValueError(_SIGNAL_LIMIT_ERROR)

        statement, parameters = self._build_filtered_query(
            base_statement=_SELECT_LATEST_BASE_SQL,
            symbol=symbol,
            signal_type=signal_type,
            strategy_name=strategy_name,
            start_time=None,
            end_time=None,
            order_direction="DESC",
            limit=limit,
        )

        rows = await self._database.fetch_all(
            statement=statement,
            parameters=parameters,
        )

        return tuple(self._from_row(row) for row in reversed(rows))

    async def get_between(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> Sequence[Signal]:
        """Return signals within an inclusive datetime range."""
        if start_time > end_time:
            raise ValueError(_SIGNAL_TIME_RANGE_ERROR)

        statement, parameters = self._build_filtered_query(
            base_statement=_SELECT_BETWEEN_BASE_SQL,
            symbol=symbol,
            signal_type=signal_type,
            strategy_name=strategy_name,
            start_time=start_time,
            end_time=end_time,
            order_direction="ASC",
            limit=None,
        )

        rows = await self._database.fetch_all(
            statement=statement,
            parameters=parameters,
        )

        return tuple(self._from_row(row) for row in rows)

    async def get_latest_for_symbol(
        self,
        *,
        symbol: str,
        strategy_name: str | None = None,
    ) -> Signal | None:
        """Return the latest signal for a trading symbol."""
        normalized_symbol = self._normalize_symbol(symbol)

        if strategy_name is None:
            statement = _SELECT_LATEST_FOR_SYMBOL_SQL
            parameters: QueryParameters = (normalized_symbol,)
        else:
            statement = _SELECT_LATEST_FOR_SYMBOL_STRATEGY_SQL
            parameters = (
                normalized_symbol,
                self._normalize_strategy_name(strategy_name),
            )

        row = await self._database.fetch_one(
            statement=statement,
            parameters=parameters,
        )

        if row is None:
            return None

        return self._from_row(row)

    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
    ) -> int:
        """Delete signals older than a datetime boundary."""
        before_value = self._datetime_to_text(
            before,
            label="deletion boundary",
        )

        if symbol is None:
            statement = _DELETE_BEFORE_SQL
            parameters: QueryParameters = (before_value,)
        else:
            statement = _DELETE_BEFORE_SYMBOL_SQL
            parameters = (
                before_value,
                self._normalize_symbol(symbol),
            )

        return await self._database.execute(
            statement=statement,
            parameters=parameters,
        )

    async def count(
        self,
        *,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> int:
        """Count stored trading signals."""
        statement, parameters = self._build_count_query(
            symbol=symbol,
            signal_type=signal_type,
            strategy_name=strategy_name,
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

    @classmethod
    def _to_parameters(
        cls,
        signal: Signal,
    ) -> SignalParameters:
        """Convert a signal into SQLite parameters."""
        return (
            cls._normalize_symbol(signal.symbol),
            cls._normalize_strategy_name(signal.strategy_name),
            cls._datetime_to_text(
                signal.generated_at,
                label="generated time",
            ),
            signal.signal_type.value,
            cls._decimal_to_text(signal.price),
            cls._decimal_to_text(signal.confidence),
            signal.reason,
        )

    @classmethod
    def _from_row(
        cls,
        row: Row,
    ) -> Signal:
        """Map a SQLite row into a Signal model."""
        return Signal(
            symbol=cls._get_string(
                row,
                column="symbol",
            ),
            strategy_name=cls._get_string(
                row,
                column="strategy_name",
            ),
            generated_at=cls._get_datetime(
                row,
                column="generated_at",
            ),
            signal_type=SignalType(
                cls._get_string(
                    row,
                    column="signal_type",
                )
            ),
            price=cls._get_decimal(
                row,
                column="price",
            ),
            confidence=cls._get_decimal(
                row,
                column="confidence",
            ),
            reason=cls._get_optional_string(
                row,
                column="reason",
            ),
        )

    @classmethod
    def _build_filtered_query(
        cls,
        *,
        base_statement: str,
        symbol: str | None,
        signal_type: SignalType | None,
        strategy_name: str | None,
        start_time: datetime | None,
        end_time: datetime | None,
        order_direction: str,
        limit: int | None,
    ) -> tuple[str, QueryParameters]:
        """Build a filtered signal query."""
        conditions: list[str] = []
        parameters: list[object] = []

        if symbol is not None:
            conditions.append("symbol = ?")
            parameters.append(cls._normalize_symbol(symbol))

        if signal_type is not None:
            conditions.append("signal_type = ?")
            parameters.append(signal_type.value)

        if strategy_name is not None:
            conditions.append("strategy_name = ?")
            parameters.append(cls._normalize_strategy_name(strategy_name))

        if start_time is not None:
            conditions.append("generated_at >= ?")
            parameters.append(
                cls._datetime_to_text(
                    start_time,
                    label="start time",
                )
            )

        if end_time is not None:
            conditions.append("generated_at <= ?")
            parameters.append(
                cls._datetime_to_text(
                    end_time,
                    label="end time",
                )
            )

        statement_parts: list[str] = [
            base_statement.strip(),
        ]

        if conditions:
            statement_parts.append("WHERE " + " AND ".join(conditions))

        statement_parts.append(f"ORDER BY generated_at {order_direction}")

        if limit is not None:
            statement_parts.append("LIMIT ?")
            parameters.append(limit)

        statement = "\n".join(statement_parts) + ";"

        return statement, tuple(parameters)

    @classmethod
    def _build_count_query(
        cls,
        *,
        symbol: str | None,
        signal_type: SignalType | None,
        strategy_name: str | None,
    ) -> tuple[str, QueryParameters]:
        """Build a count query from optional filters."""
        conditions: list[str] = []
        parameters: list[object] = []

        if symbol is not None:
            conditions.append("symbol = ?")
            parameters.append(cls._normalize_symbol(symbol))

        if signal_type is not None:
            conditions.append("signal_type = ?")
            parameters.append(signal_type.value)

        if strategy_name is not None:
            conditions.append("strategy_name = ?")
            parameters.append(cls._normalize_strategy_name(strategy_name))

        statement = _COUNT_BASE_SQL.strip()

        if conditions:
            statement += "\nWHERE " + " AND ".join(conditions)

        return statement + ";", tuple(parameters)

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
    def _normalize_strategy_name(
        strategy_name: str,
    ) -> str:
        """Normalize and validate a strategy name."""
        normalized_strategy_name = strategy_name.strip()

        if not normalized_strategy_name:
            raise ValueError(_STRATEGY_NAME_ERROR)

        return normalized_strategy_name

    @staticmethod
    def _datetime_to_text(
        value: datetime,
        *,
        label: str,
    ) -> str:
        """Convert a timezone-aware datetime into ISO-8601 text."""
        if value.tzinfo is None:
            raise ValueError(
                _DATETIME_ERROR_TEMPLATE.format(
                    label=label,
                )
            )

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
        """Return a timezone-aware datetime from a SQLite row."""
        result = datetime.fromisoformat(
            cls._get_string(
                row,
                column=column,
            )
        )

        if result.tzinfo is None:
            raise ValueError(
                _DATETIME_ERROR_TEMPLATE.format(
                    label=column,
                )
            )

        return result

    @classmethod
    def _get_decimal(
        cls,
        row: Row,
        *,
        column: str,
    ) -> Decimal:
        """Return a Decimal from a SQLite text column."""
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
        """Return a string from a SQLite row."""
        value: object = row[column]

        if not isinstance(value, str):
            raise TypeError(f"SQLite column {column!r} must contain text")

        return value

    @staticmethod
    def _get_optional_string(
        row: Row,
        *,
        column: str,
    ) -> str | None:
        """Return an optional string from a SQLite row."""
        value: object = row[column]

        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"SQLite column {column!r} must contain text or NULL")

        return value

    @staticmethod
    def _get_integer(
        row: Row,
        *,
        column: str,
    ) -> int:
        """Return an integer from a SQLite row."""
        value: object = row[column]

        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"SQLite column {column!r} must contain an integer")

        return value
