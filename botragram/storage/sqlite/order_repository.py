"""
Botragram

Description:
    SQLite trading order repository implementation.

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
from botragram.enums import OrderSide, OrderStatus, OrderType
from botragram.models import Order
from botragram.repositories import OrderRepository
from botragram.storage.sqlite.database import SQLiteDatabase

__all__ = [
    "SQLiteOrderRepository",
]


# =============================================================================
# Constants
# =============================================================================
_ORDER_LIMIT_ERROR: Final[str] = "Order limit must be greater than zero"
_ORDER_TIME_RANGE_ERROR: Final[str] = "Order start time must not be after end time"
_SYMBOL_ERROR: Final[str] = "Trading symbol must not be empty"
_ORDER_ID_ERROR: Final[str] = "Order identifier must not be empty"
_DATETIME_ERROR_TEMPLATE: Final[str] = "SQLite order {label} must be timezone-aware"
_RECORD_COUNT_COLUMN: Final[str] = "record_count"

_OPEN_ORDER_STATUSES: Final[tuple[OrderStatus, ...]] = (
    OrderStatus.NEW,
    OrderStatus.PARTIALLY_FILLED,
)


# =============================================================================
# SQL Statements
# =============================================================================
_UPSERT_ORDER_SQL: Final[str] = """
INSERT INTO orders (
    symbol,
    order_id,
    side,
    order_type,
    status,
    quantity,
    executed_quantity,
    created_at,
    updated_at,
    price,
    stop_price,
    client_order_id
)
VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
)
ON CONFLICT (
    symbol,
    order_id
)
DO UPDATE SET
    side = excluded.side,
    order_type = excluded.order_type,
    status = excluded.status,
    quantity = excluded.quantity,
    executed_quantity = excluded.executed_quantity,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at,
    price = excluded.price,
    stop_price = excluded.stop_price,
    client_order_id = excluded.client_order_id;
"""

_SELECT_ORDER_COLUMNS: Final[str] = """
SELECT
    symbol,
    order_id,
    side,
    order_type,
    status,
    quantity,
    executed_quantity,
    created_at,
    updated_at,
    price,
    stop_price,
    client_order_id
FROM orders
"""

_SELECT_BY_ID_SQL: Final[str] = (
    _SELECT_ORDER_COLUMNS
    + """
WHERE
    order_id = ?
ORDER BY created_at ASC;
"""
)

_SELECT_BY_SYMBOL_AND_ID_SQL: Final[str] = (
    _SELECT_ORDER_COLUMNS
    + """
WHERE
    symbol = ?
    AND order_id = ?
LIMIT 1;
"""
)

_SELECT_OPEN_ORDERS_SQL: Final[str] = (
    _SELECT_ORDER_COLUMNS
    + """
WHERE status IN (?, ?)
ORDER BY created_at ASC;
"""
)

_SELECT_OPEN_ORDERS_BY_SYMBOL_SQL: Final[str] = (
    _SELECT_ORDER_COLUMNS
    + """
WHERE
    symbol = ?
    AND status IN (?, ?)
ORDER BY created_at ASC;
"""
)

_DELETE_BEFORE_SQL: Final[str] = """
DELETE FROM orders
WHERE created_at < ?;
"""

_DELETE_BEFORE_SYMBOL_SQL: Final[str] = """
DELETE FROM orders
WHERE
    created_at < ?
    AND symbol = ?;
"""

_COUNT_BASE_SQL: Final[str] = """
SELECT COUNT(*) AS record_count
FROM orders
"""


# =============================================================================
# Type Aliases
# =============================================================================
type OrderParameters = tuple[
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
    str | None,
    str | None,
]

type QueryParameters = tuple[object, ...]


# =============================================================================
# Repository Implementations
# =============================================================================
class SQLiteOrderRepository(OrderRepository):
    """Persist trading orders in SQLite."""

    __slots__ = ("_database",)

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
    ) -> None:
        """Initialize the SQLite order repository.

        Args:
            database: Connected SQLite database manager.
        """
        self._database = database

    async def save(
        self,
        *,
        order: Order,
    ) -> None:
        """Persist or replace a trading order."""
        await self._database.execute(
            statement=_UPSERT_ORDER_SQL,
            parameters=self._to_parameters(order),
        )

    async def save_many(
        self,
        *,
        orders: Sequence[Order],
    ) -> None:
        """Persist or replace multiple trading orders."""
        parameter_rows: tuple[OrderParameters, ...] = tuple(
            self._to_parameters(order) for order in orders
        )

        await self._database.execute_many(
            statement=_UPSERT_ORDER_SQL,
            parameter_rows=parameter_rows,
        )

    async def get_by_id(
        self,
        *,
        order_id: str,
        symbol: str | None = None,
    ) -> Order | None:
        """Return an order by identifier."""
        normalized_order_id = self._normalize_order_id(order_id)

        if symbol is not None:
            row = await self._database.fetch_one(
                statement=_SELECT_BY_SYMBOL_AND_ID_SQL,
                parameters=(
                    self._normalize_symbol(symbol),
                    normalized_order_id,
                ),
            )

            if row is None:
                return None

            return self._from_row(row)

        rows = await self._database.fetch_all(
            statement=_SELECT_BY_ID_SQL,
            parameters=(normalized_order_id,),
        )

        matching_row: Row | None = None

        for row in rows:
            if matching_row is not None:
                raise RuntimeError(
                    f"Multiple orders use identifier {normalized_order_id!r}"
                )

            matching_row = row

        if matching_row is None:
            return None

        return self._from_row(matching_row)

    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        side: OrderSide | None = None,
        order_type: OrderType | None = None,
        status: OrderStatus | None = None,
    ) -> Sequence[Order]:
        """Return the latest trading orders."""
        if limit <= 0:
            raise ValueError(_ORDER_LIMIT_ERROR)

        statement, parameters = self._build_filtered_query(
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
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
        order_type: OrderType | None = None,
        status: OrderStatus | None = None,
    ) -> Sequence[Order]:
        """Return orders created within an inclusive datetime range."""
        if start_time > end_time:
            raise ValueError(_ORDER_TIME_RANGE_ERROR)

        statement, parameters = self._build_filtered_query(
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
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

    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open orders."""
        status_values = tuple(status.value for status in _OPEN_ORDER_STATUSES)

        if symbol is None:
            statement = _SELECT_OPEN_ORDERS_SQL
            parameters: QueryParameters = status_values
        else:
            statement = _SELECT_OPEN_ORDERS_BY_SYMBOL_SQL
            parameters = (
                self._normalize_symbol(symbol),
                *status_values,
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
        """Delete orders older than a datetime boundary."""
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
        order_type: OrderType | None = None,
        status: OrderStatus | None = None,
    ) -> int:
        """Count stored trading orders."""
        statement, parameters = self._build_count_query(
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
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
        order: Order,
    ) -> OrderParameters:
        """Convert an order into SQLite parameters."""
        return (
            cls._normalize_symbol(order.symbol),
            cls._normalize_order_id(order.order_id),
            order.side.value,
            order.order_type.value,
            order.status.value,
            cls._decimal_to_text(order.quantity),
            cls._decimal_to_text(order.executed_quantity),
            cls._datetime_to_text(
                order.created_at,
                label="creation time",
            ),
            cls._datetime_to_text(
                order.updated_at,
                label="update time",
            ),
            cls._optional_decimal_to_text(order.price),
            cls._optional_decimal_to_text(order.stop_price),
            order.client_order_id,
        )

    @classmethod
    def _from_row(
        cls,
        row: Row,
    ) -> Order:
        """Map a SQLite row into an Order model."""
        return Order(
            symbol=cls._get_string(
                row,
                column="symbol",
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
            order_type=OrderType(
                cls._get_string(
                    row,
                    column="order_type",
                )
            ),
            status=OrderStatus(
                cls._get_string(
                    row,
                    column="status",
                )
            ),
            quantity=cls._get_decimal(
                row,
                column="quantity",
            ),
            executed_quantity=cls._get_decimal(
                row,
                column="executed_quantity",
            ),
            created_at=cls._get_datetime(
                row,
                column="created_at",
            ),
            updated_at=cls._get_datetime(
                row,
                column="updated_at",
            ),
            price=cls._get_optional_decimal(
                row,
                column="price",
            ),
            stop_price=cls._get_optional_decimal(
                row,
                column="stop_price",
            ),
            client_order_id=cls._get_optional_string(
                row,
                column="client_order_id",
            ),
        )

    @classmethod
    def _build_filtered_query(
        cls,
        *,
        symbol: str | None,
        side: OrderSide | None,
        order_type: OrderType | None,
        status: OrderStatus | None,
        start_time: datetime | None,
        end_time: datetime | None,
        order_direction: str,
        limit: int | None,
    ) -> tuple[str, QueryParameters]:
        """Build a filtered order query."""
        conditions: list[str] = []
        parameters: list[object] = []

        if symbol is not None:
            conditions.append("symbol = ?")
            parameters.append(cls._normalize_symbol(symbol))

        if side is not None:
            conditions.append("side = ?")
            parameters.append(side.value)

        if order_type is not None:
            conditions.append("order_type = ?")
            parameters.append(order_type.value)

        if status is not None:
            conditions.append("status = ?")
            parameters.append(status.value)

        if start_time is not None:
            conditions.append("created_at >= ?")
            parameters.append(
                cls._datetime_to_text(
                    start_time,
                    label="start time",
                )
            )

        if end_time is not None:
            conditions.append("created_at <= ?")
            parameters.append(
                cls._datetime_to_text(
                    end_time,
                    label="end time",
                )
            )

        statement_parts: list[str] = [
            _SELECT_ORDER_COLUMNS.strip(),
        ]

        if conditions:
            statement_parts.append("WHERE " + " AND ".join(conditions))

        statement_parts.append(f"ORDER BY created_at {order_direction}")

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
        order_type: OrderType | None,
        status: OrderStatus | None,
    ) -> tuple[str, QueryParameters]:
        """Build an order count query."""
        conditions: list[str] = []
        parameters: list[object] = []

        if symbol is not None:
            conditions.append("symbol = ?")
            parameters.append(cls._normalize_symbol(symbol))

        if side is not None:
            conditions.append("side = ?")
            parameters.append(side.value)

        if order_type is not None:
            conditions.append("order_type = ?")
            parameters.append(order_type.value)

        if status is not None:
            conditions.append("status = ?")
            parameters.append(status.value)

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
    def _normalize_order_id(
        order_id: str,
    ) -> str:
        """Normalize and validate an order identifier."""
        normalized_order_id = order_id.strip()

        if not normalized_order_id:
            raise ValueError(_ORDER_ID_ERROR)

        return normalized_order_id

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
