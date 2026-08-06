"""
Botragram

Description:
    SQLite executed trade repository implementation.

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
from botragram.enums import OrderSide
from botragram.models import Trade
from botragram.repositories import TradeRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = [
    "SQLiteTradeRepository",
]


# =============================================================================
# Constants
# =============================================================================
_TRADE_LIMIT_ERROR: Final[str] = "Trade limit must be greater than zero"
_TRADE_TIME_RANGE_ERROR: Final[str] = "Trade start time must not be after end time"
_SYMBOL_ERROR: Final[str] = "Trading symbol must not be empty"
_TRADE_ID_ERROR: Final[str] = "Trade identifier must not be empty"
_ORDER_ID_ERROR: Final[str] = "Order identifier must not be empty"
_FEE_ASSET_ERROR: Final[str] = "Fee asset must not be empty"
_DATETIME_ERROR_TEMPLATE: Final[str] = "SQLite trade {label} must be timezone-aware"
_RECORD_COUNT_COLUMN: Final[str] = "record_count"


# =============================================================================
# SQL Statements
# =============================================================================
_UPSERT_TRADE_SQL: Final[str] = """
INSERT INTO trades (
    symbol,
    trade_id,
    order_id,
    side,
    price,
    quantity,
    quote_quantity,
    fee,
    fee_asset,
    realized_pnl,
    executed_at
)
VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
)
ON CONFLICT (
    symbol,
    trade_id
)
DO UPDATE SET
    order_id = excluded.order_id,
    side = excluded.side,
    price = excluded.price,
    quantity = excluded.quantity,
    quote_quantity = excluded.quote_quantity,
    fee = excluded.fee,
    fee_asset = excluded.fee_asset,
    realized_pnl = excluded.realized_pnl,
    executed_at = excluded.executed_at;
"""

_SELECT_TRADE_COLUMNS: Final[str] = """
SELECT
    symbol,
    trade_id,
    order_id,
    side,
    price,
    quantity,
    quote_quantity,
    fee,
    fee_asset,
    realized_pnl,
    executed_at
FROM trades
"""

_SELECT_BY_ID_SQL: Final[str] = (
    _SELECT_TRADE_COLUMNS
    + """
WHERE trade_id = ?
ORDER BY executed_at ASC;
"""
)

_SELECT_BY_SYMBOL_AND_ID_SQL: Final[str] = (
    _SELECT_TRADE_COLUMNS
    + """
WHERE
    symbol = ?
    AND trade_id = ?
LIMIT 1;
"""
)

_SELECT_BY_ORDER_ID_SQL: Final[str] = (
    _SELECT_TRADE_COLUMNS
    + """
WHERE order_id = ?
ORDER BY executed_at ASC;
"""
)

_SELECT_BY_ORDER_ID_AND_SYMBOL_SQL: Final[str] = (
    _SELECT_TRADE_COLUMNS
    + """
WHERE
    order_id = ?
    AND symbol = ?
ORDER BY executed_at ASC;
"""
)

_DELETE_BEFORE_SQL: Final[str] = """
DELETE FROM trades
WHERE executed_at < ?;
"""

_DELETE_BEFORE_SYMBOL_SQL: Final[str] = """
DELETE FROM trades
WHERE
    executed_at < ?
    AND symbol = ?;
"""

_COUNT_BASE_SQL: Final[str] = """
SELECT COUNT(*) AS record_count
FROM trades
"""


# =============================================================================
# Type Aliases
# =============================================================================
type TradeParameters = tuple[
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str | None,
    str,
]

type QueryParameters = tuple[object, ...]


# =============================================================================
# Repository Implementations
# =============================================================================
class SQLiteTradeRepository(TradeRepository):
    """Persist executed trades in SQLite."""

    __slots__ = ("_database",)

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
    ) -> None:
        """Initialize the SQLite trade repository.

        Args:
            database: Connected SQLite database manager.
        """
        self._database = database

    async def save(
        self,
        *,
        trade: Trade,
    ) -> None:
        """Persist or replace an executed trade."""
        await self._database.execute(
            statement=_UPSERT_TRADE_SQL,
            parameters=self._to_parameters(trade),
        )

    async def save_many(
        self,
        *,
        trades: Sequence[Trade],
    ) -> None:
        """Persist or replace multiple executed trades."""
        parameter_rows: tuple[TradeParameters, ...] = tuple(
            self._to_parameters(trade) for trade in trades
        )

        await self._database.execute_many(
            statement=_UPSERT_TRADE_SQL,
            parameter_rows=parameter_rows,
        )

    async def get_by_id(
        self,
        *,
        trade_id: str,
        symbol: str | None = None,
    ) -> Trade | None:
        """Return a trade by identifier."""
        normalized_trade_id = self._normalize_trade_id(trade_id)

        if symbol is not None:
            row = await self._database.fetch_one(
                statement=_SELECT_BY_SYMBOL_AND_ID_SQL,
                parameters=(
                    self._normalize_symbol(symbol),
                    normalized_trade_id,
                ),
            )

            if row is None:
                return None

            return self._from_row(row)

        rows = await self._database.fetch_all(
            statement=_SELECT_BY_ID_SQL,
            parameters=(normalized_trade_id,),
        )

        matching_row: Row | None = None

        for row in rows:
            if matching_row is not None:
                raise RuntimeError(
                    f"Multiple trades use identifier {normalized_trade_id!r}"
                )

            matching_row = row

        if matching_row is None:
            return None

        return self._from_row(matching_row)

    async def get_by_order_id(
        self,
        *,
        order_id: str,
        symbol: str | None = None,
    ) -> Sequence[Trade]:
        """Return all fills associated with an order."""
        normalized_order_id = self._normalize_order_id(order_id)

        if symbol is None:
            statement = _SELECT_BY_ORDER_ID_SQL
            parameters: QueryParameters = (normalized_order_id,)
        else:
            statement = _SELECT_BY_ORDER_ID_AND_SYMBOL_SQL
            parameters = (
                normalized_order_id,
                self._normalize_symbol(symbol),
            )

        rows = await self._database.fetch_all(
            statement=statement,
            parameters=parameters,
        )

        return tuple(self._from_row(row) for row in rows)

    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        side: OrderSide | None = None,
    ) -> Sequence[Trade]:
        """Return the latest executed trades."""
        if limit <= 0:
            raise ValueError(_TRADE_LIMIT_ERROR)

        statement, parameters = self._build_filtered_query(
            symbol=symbol,
            side=side,
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
        side: OrderSide | None = None,
    ) -> Sequence[Trade]:
        """Return trades within an inclusive datetime range."""
        if start_time > end_time:
            raise ValueError(_TRADE_TIME_RANGE_ERROR)

        statement, parameters = self._build_filtered_query(
            symbol=symbol,
            side=side,
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

    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
    ) -> int:
        """Delete trades older than a datetime boundary."""
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
        side: OrderSide | None = None,
    ) -> int:
        """Count stored executed trades."""
        statement, parameters = self._build_count_query(
            symbol=symbol,
            side=side,
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
        trade: Trade,
    ) -> TradeParameters:
        """Convert a trade into SQLite parameters."""
        return (
            cls._normalize_symbol(trade.symbol),
            cls._normalize_trade_id(trade.trade_id),
            cls._normalize_order_id(trade.order_id),
            trade.side.value,
            cls._decimal_to_text(trade.price),
            cls._decimal_to_text(trade.quantity),
            cls._decimal_to_text(trade.quote_quantity),
            cls._decimal_to_text(trade.fee),
            cls._normalize_fee_asset(trade.fee_asset),
            cls._optional_decimal_to_text(trade.realized_pnl),
            cls._datetime_to_text(
                trade.executed_at,
                label="execution time",
            ),
        )

    @classmethod
    def _from_row(
        cls,
        row: Row,
    ) -> Trade:
        """Map a SQLite row into a Trade model."""
        return Trade(
            symbol=cls._get_string(
                row,
                column="symbol",
            ),
            trade_id=cls._get_string(
                row,
                column="trade_id",
            ),
            order_id=cls._get_string(
                row,
                column="order_id",
            ),
            side=OrderSide(
                cls._get_string(
                    row,
                    column="side",
                )
            ),
            price=cls._get_decimal(
                row,
                column="price",
            ),
            quantity=cls._get_decimal(
                row,
                column="quantity",
            ),
            quote_quantity=cls._get_decimal(
                row,
                column="quote_quantity",
            ),
            fee=cls._get_decimal(
                row,
                column="fee",
            ),
            fee_asset=cls._get_string(
                row,
                column="fee_asset",
            ),
            realized_pnl=cls._get_optional_decimal(
                row,
                column="realized_pnl",
            ),
            executed_at=cls._get_datetime(
                row,
                column="executed_at",
            ),
        )

    @classmethod
    def _build_filtered_query(
        cls,
        *,
        symbol: str | None,
        side: OrderSide | None,
        start_time: datetime | None,
        end_time: datetime | None,
        order_direction: str,
        limit: int | None,
    ) -> tuple[str, QueryParameters]:
        """Build a filtered trade query."""
        conditions: list[str] = []
        parameters: list[object] = []

        if symbol is not None:
            conditions.append("symbol = ?")
            parameters.append(cls._normalize_symbol(symbol))

        if side is not None:
            conditions.append("side = ?")
            parameters.append(side.value)

        if start_time is not None:
            conditions.append("executed_at >= ?")
            parameters.append(
                cls._datetime_to_text(
                    start_time,
                    label="start time",
                )
            )

        if end_time is not None:
            conditions.append("executed_at <= ?")
            parameters.append(
                cls._datetime_to_text(
                    end_time,
                    label="end time",
                )
            )

        statement_parts: list[str] = [
            _SELECT_TRADE_COLUMNS.strip(),
        ]

        if conditions:
            statement_parts.append("WHERE " + " AND ".join(conditions))

        statement_parts.append(f"ORDER BY executed_at {order_direction}")

        if limit is not None:
            statement_parts.append("LIMIT ?")
            parameters.append(limit)

        return (
            "\n".join(statement_parts) + ";",
            tuple(parameters),
        )

    @classmethod
    def _build_count_query(
        cls,
        *,
        symbol: str | None,
        side: OrderSide | None,
    ) -> tuple[str, QueryParameters]:
        """Build a trade count query."""
        conditions: list[str] = []
        parameters: list[object] = []

        if symbol is not None:
            conditions.append("symbol = ?")
            parameters.append(cls._normalize_symbol(symbol))

        if side is not None:
            conditions.append("side = ?")
            parameters.append(side.value)

        statement = _COUNT_BASE_SQL.strip()

        if conditions:
            statement += "\nWHERE " + " AND ".join(conditions)

        return (
            statement + ";",
            tuple(parameters),
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
    def _normalize_trade_id(
        trade_id: str,
    ) -> str:
        """Normalize and validate a trade identifier."""
        normalized_trade_id = trade_id.strip()

        if not normalized_trade_id:
            raise ValueError(_TRADE_ID_ERROR)

        return normalized_trade_id

    @staticmethod
    def _normalize_order_id(
        order_id: str,
    ) -> str:
        """Normalize and validate an order identifier."""
        normalized_order_id = order_id.strip()

        if not normalized_order_id:
            raise ValueError(_ORDER_ID_ERROR)

        return normalized_order_id

    @staticmethod
    def _normalize_fee_asset(
        fee_asset: str,
    ) -> str:
        """Normalize and validate a fee asset symbol."""
        normalized_fee_asset = fee_asset.strip().upper()

        if not normalized_fee_asset:
            raise ValueError(_FEE_ASSET_ERROR)

        return normalized_fee_asset

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
    def _optional_decimal_to_text(
        cls,
        value: Decimal | None,
    ) -> str | None:
        """Convert an optional Decimal into exact text."""
        if value is None:
            return None

        return cls._decimal_to_text(value)

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

    @classmethod
    def _get_optional_decimal(
        cls,
        row: Row,
        *,
        column: str,
    ) -> Decimal | None:
        """Return an optional Decimal from a SQLite row."""
        value = cls._get_optional_string(
            row,
            column=column,
        )

        if value is None:
            return None

        return Decimal(value)

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
