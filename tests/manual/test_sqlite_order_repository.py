"""
Botragram

Description:
    Manual SQLite order repository smoke test.

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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OrderSide, OrderStatus, OrderType
from botragram.models import Order
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteOrderRepository,
)

# =============================================================================
# Constants
# =============================================================================
_SYMBOL = "BTCUSDT"
_OTHER_SYMBOL = "ETHUSDT"

_EXPECTED_SCHEMA_VERSION = 8
_EXPECTED_TOTAL_COUNT = 3


# =============================================================================
# Test Helpers
# =============================================================================
def _create_order(
    *,
    order_id: str,
    symbol: str,
    side: OrderSide,
    order_type: OrderType,
    status: OrderStatus,
    quantity: Decimal,
    executed_quantity: Decimal,
    created_at: datetime,
    updated_at: datetime,
    price: Decimal | None = None,
    stop_price: Decimal | None = None,
) -> Order:
    """Create an order for the SQLite smoke test."""
    return Order(
        order_id=order_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        status=status,
        quantity=quantity,
        executed_quantity=executed_quantity,
        created_at=created_at,
        updated_at=updated_at,
        price=price,
        stop_price=stop_price,
    )


# =============================================================================
# Manual Test
# =============================================================================
async def _run_test() -> None:
    """Run the SQLite order repository smoke test."""
    base_time = datetime(
        2026,
        8,
        6,
        15,
        0,
        tzinfo=timezone.utc,
    )

    order_one = _create_order(
        order_id="1001",
        symbol=_SYMBOL,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        status=OrderStatus.NEW,
        quantity=Decimal("0.10"),
        executed_quantity=Decimal("0"),
        created_at=base_time,
        updated_at=base_time,
        price=Decimal("60000"),
    )

    order_two = _create_order(
        order_id="1002",
        symbol=_SYMBOL,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        quantity=Decimal("0.05"),
        executed_quantity=Decimal("0.05"),
        created_at=base_time + timedelta(minutes=1),
        updated_at=base_time + timedelta(minutes=1),
    )

    order_three = _create_order(
        order_id="1003",
        symbol=_OTHER_SYMBOL,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        status=OrderStatus.PARTIALLY_FILLED,
        quantity=Decimal("1"),
        executed_quantity=Decimal("0.40"),
        created_at=base_time + timedelta(minutes=2),
        updated_at=base_time + timedelta(minutes=2),
        price=Decimal("3000"),
        stop_price=Decimal("2900"),
    )

    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "botragram_order_test.db"

        async with SQLiteDatabase(
            database_path=database_path,
        ) as database:
            migration_manager = SQLiteMigrationManager(
                database=database,
            )

            schema_version = await migration_manager.initialize()

            assert schema_version == _EXPECTED_SCHEMA_VERSION

            repository = SQLiteOrderRepository(
                database=database,
            )

            await repository.save_many(
                orders=(
                    order_one,
                    order_two,
                    order_three,
                ),
            )

            total_count = await repository.count()

            assert total_count == _EXPECTED_TOTAL_COUNT

            symbol_count = await repository.count(
                symbol=_SYMBOL,
            )

            assert symbol_count == 2

            filled_count = await repository.count(
                status=OrderStatus.FILLED,
            )

            assert filled_count == 1

            buy_count = await repository.count(
                side=OrderSide.BUY,
            )

            assert buy_count == 2

            stored_order = await repository.get_by_id(
                order_id="1001",
                symbol=_SYMBOL,
            )

            assert stored_order == order_one

            stored_without_symbol = await repository.get_by_id(
                order_id="1002",
            )

            assert stored_without_symbol == order_two

            latest = await repository.get_latest(
                limit=1,
            )

            assert latest == (order_three,)

            latest_for_symbol = await repository.get_latest(
                limit=1,
                symbol=_SYMBOL,
            )

            assert latest_for_symbol == (order_two,)

            orders_between = await repository.get_between(
                start_time=base_time,
                end_time=base_time + timedelta(minutes=1),
            )

            assert orders_between == (
                order_one,
                order_two,
            )

            open_orders = await repository.get_open_orders()

            assert open_orders == (
                order_one,
                order_three,
            )

            open_symbol_orders = await repository.get_open_orders(
                symbol=_SYMBOL,
            )

            assert open_symbol_orders == (order_one,)

            updated_order = _create_order(
                order_id="1001",
                symbol=_SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.FILLED,
                quantity=Decimal("0.10"),
                executed_quantity=Decimal("0.10"),
                created_at=base_time,
                updated_at=base_time + timedelta(minutes=3),
                price=Decimal("60000"),
            )

            await repository.save(
                order=updated_order,
            )

            updated_result = await repository.get_by_id(
                order_id="1001",
                symbol=_SYMBOL,
            )

            assert updated_result == updated_order

            open_orders_after_update = await repository.get_open_orders()

            assert open_orders_after_update == (order_three,)

            deleted_count = await repository.delete_before(
                before=base_time + timedelta(seconds=30),
                symbol=_SYMBOL,
            )

            assert deleted_count == 1

            remaining_count = await repository.count()

            assert remaining_count == 2

            print(
                "SQLite order repository smoke test passed:",
                {
                    "schema_version": schema_version,
                    "total_inserted": total_count,
                    "remaining": remaining_count,
                },
            )


# =============================================================================
# Entry Point
# =============================================================================
def main() -> None:
    """Run the manual test."""
    asyncio.run(_run_test())


if __name__ == "__main__":
    main()
