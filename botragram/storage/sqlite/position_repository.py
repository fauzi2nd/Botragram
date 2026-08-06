"""
Botragram

Description:
    SQLite trading position repository implementation.

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
from botragram.enums import PositionSide
from botragram.models import Position
from botragram.repositories import PositionRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = [
    "SQLitePositionRepository",
]


# =============================================================================
# Constants
# =============================================================================
_SYMBOL_ERROR: Final[str] = "Trading symbol must not be empty"
_DATETIME_ERROR_TEMPLATE: Final[str] = "SQLite position {label} must be timezone-aware"
_RECORD_COUNT_COLUMN: Final[str] = "record_count"


# =============================================================================
# SQL Statements
# =============================================================================
_UPSERT_POSITION_SQL: Final[str] = """
INSERT INTO positions (
    symbol,
    side,
    quantity,
    entry_price,
    current_price,
    unrealized_pnl,
    leverage,
    opened_at,
    updated_at
)
VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?
)
ON CONFLICT (
    symbol
)
DO UPDATE SET
    side = excluded.side,
    quantity = excluded.quantity,
    entry_price = excluded.entry_price,
    current_price = excluded.current_price,
    unrealized_pnl = excluded.unrealized_pnl,
    leverage = excluded.leverage,
    opened_at = excluded.opened_at,
    updated_at = excluded.updated_at;
"""

_UPDATE_POSITION_SQL: Final[str] = """
UPDATE positions
SET
    side = ?,
    quantity = ?,
    entry_price = ?,
    current_price = ?,
    unrealized_pnl = ?,
    leverage = ?,
    opened_at = ?,
    updated_at = ?
WHERE symbol = ?;
"""

_SELECT_POSITION_COLUMNS: Final[str] = """
SELECT
    symbol,
    side,
    quantity,
    entry_price,
    current_price,
    unrealized_pnl,
    leverage,
    opened_at,
    updated_at
FROM positions
"""

_SELECT_BY_SYMBOL_SQL: Final[str] = (
    _SELECT_POSITION_COLUMNS
    + """
WHERE symbol = ?
LIMIT 1;
"""
)

_SELECT_ALL_SQL: Final[str] = (
    _SELECT_POSITION_COLUMNS
    + """
ORDER BY
    symbol ASC,
    opened_at ASC;
"""
)

_SELECT_BY_SIDE_SQL: Final[str] = (
    _SELECT_POSITION_COLUMNS
    + """
WHERE side = ?
ORDER BY
    symbol ASC,
    opened_at ASC;
"""
)

_SELECT_OPEN_POSITIONS_SQL: Final[str] = (
    _SELECT_POSITION_COLUMNS
    + """
WHERE CAST(quantity AS REAL) > 0
ORDER BY
    symbol ASC,
    opened_at ASC;
"""
)

_DELETE_BY_SYMBOL_SQL: Final[str] = """
DELETE FROM positions
WHERE symbol = ?;
"""

_DELETE_ALL_SQL: Final[str] = """
DELETE FROM positions;
"""

_COUNT_SQL: Final[str] = """
SELECT COUNT(*) AS record_count
FROM positions;
"""


# =============================================================================
# Type Aliases
# =============================================================================
type PositionParameters = tuple[
    str,
    str,
    str,
    str,
    str,
    str,
    int,
    str,
    str,
]

type PositionUpdateParameters = tuple[
    str,
    str,
    str,
    str,
    str,
    int,
    str,
    str,
    str,
]


# =============================================================================
# Repository Implementations
# =============================================================================
class SQLitePositionRepository(PositionRepository):
    """Persist trading positions in SQLite."""

    __slots__ = ("_database",)

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
    ) -> None:
        """Initialize the SQLite position repository.

        Args:
            database: Connected SQLite database manager.
        """
        self._database = database

    async def save(
        self,
        *,
        position: Position,
    ) -> None:
        """Persist or replace a trading position."""
        await self._database.execute(
            statement=_UPSERT_POSITION_SQL,
            parameters=self._to_parameters(position),
        )

    async def save_many(
        self,
        *,
        positions: Sequence[Position],
    ) -> None:
        """Persist or replace multiple trading positions."""
        parameter_rows: tuple[PositionParameters, ...] = tuple(
            self._to_parameters(position) for position in positions
        )

        await self._database.execute_many(
            statement=_UPSERT_POSITION_SQL,
            parameter_rows=parameter_rows,
        )

    async def get_by_symbol(
        self,
        *,
        symbol: str,
    ) -> Position | None:
        """Return the active position for a trading symbol."""
        row = await self._database.fetch_one(
            statement=_SELECT_BY_SYMBOL_SQL,
            parameters=(self._normalize_symbol(symbol),),
        )

        if row is None:
            return None

        return self._from_row(row)

    async def get_all(
        self,
    ) -> Sequence[Position]:
        """Return all stored positions."""
        rows = await self._database.fetch_all(
            statement=_SELECT_ALL_SQL,
        )

        return tuple(self._from_row(row) for row in rows)

    async def get_by_side(
        self,
        *,
        side: PositionSide,
    ) -> Sequence[Position]:
        """Return positions filtered by position side."""
        rows = await self._database.fetch_all(
            statement=_SELECT_BY_SIDE_SQL,
            parameters=(side.value,),
        )

        return tuple(self._from_row(row) for row in rows)

    async def get_open_positions(
        self,
    ) -> Sequence[Position]:
        """Return all active non-zero positions."""
        rows = await self._database.fetch_all(
            statement=_SELECT_OPEN_POSITIONS_SQL,
        )

        return tuple(self._from_row(row) for row in rows)

    async def update(
        self,
        *,
        position: Position,
    ) -> None:
        """Update an existing position.

        Raises:
            LookupError: If the position does not exist.
        """
        affected_rows = await self._database.execute(
            statement=_UPDATE_POSITION_SQL,
            parameters=self._to_update_parameters(position),
        )

        if affected_rows == 0:
            symbol = self._normalize_symbol(position.symbol)

            raise LookupError(f"Position does not exist for symbol {symbol!r}")

    async def delete(
        self,
        *,
        symbol: str,
    ) -> bool:
        """Delete a position by trading symbol."""
        affected_rows = await self._database.execute(
            statement=_DELETE_BY_SYMBOL_SQL,
            parameters=(self._normalize_symbol(symbol),),
        )

        return affected_rows > 0

    async def delete_all(
        self,
    ) -> int:
        """Delete every stored position."""
        return await self._database.execute(
            statement=_DELETE_ALL_SQL,
        )

    async def count(
        self,
    ) -> int:
        """Return the number of stored positions."""
        row = await self._database.fetch_one(
            statement=_COUNT_SQL,
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
        position: Position,
    ) -> PositionParameters:
        """Convert a position into SQLite parameters."""
        return (
            cls._normalize_symbol(position.symbol),
            position.side.value,
            cls._decimal_to_text(position.quantity),
            cls._decimal_to_text(position.entry_price),
            cls._decimal_to_text(position.current_price),
            cls._decimal_to_text(position.unrealized_pnl),
            position.leverage,
            cls._datetime_to_text(
                position.opened_at,
                label="open time",
            ),
            cls._datetime_to_text(
                position.updated_at,
                label="update time",
            ),
        )

    @classmethod
    def _to_update_parameters(
        cls,
        position: Position,
    ) -> PositionUpdateParameters:
        """Convert a position into update parameters."""
        return (
            position.side.value,
            cls._decimal_to_text(position.quantity),
            cls._decimal_to_text(position.entry_price),
            cls._decimal_to_text(position.current_price),
            cls._decimal_to_text(position.unrealized_pnl),
            position.leverage,
            cls._datetime_to_text(
                position.opened_at,
                label="open time",
            ),
            cls._datetime_to_text(
                position.updated_at,
                label="update time",
            ),
            cls._normalize_symbol(position.symbol),
        )

    @classmethod
    def _from_row(
        cls,
        row: Row,
    ) -> Position:
        """Map a SQLite row into a Position model."""
        return Position(
            symbol=cls._get_string(
                row,
                column="symbol",
            ),
            side=PositionSide(
                cls._get_string(
                    row,
                    column="side",
                )
            ),
            quantity=cls._get_decimal(
                row,
                column="quantity",
            ),
            entry_price=cls._get_decimal(
                row,
                column="entry_price",
            ),
            current_price=cls._get_decimal(
                row,
                column="current_price",
            ),
            unrealized_pnl=cls._get_decimal(
                row,
                column="unrealized_pnl",
            ),
            leverage=cls._get_integer(
                row,
                column="leverage",
            ),
            opened_at=cls._get_datetime(
                row,
                column="opened_at",
            ),
            updated_at=cls._get_datetime(
                row,
                column="updated_at",
            ),
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
        *,
        label: str,
    ) -> str:
        """Convert a timezone-aware datetime into text."""
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
        """Convert a Decimal into exact text."""
        return format(value, "f")

    @classmethod
    def _get_datetime(
        cls,
        row: Row,
        *,
        column: str,
    ) -> datetime:
        """Return a timezone-aware datetime."""
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
        """Return a Decimal from a text column."""
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
