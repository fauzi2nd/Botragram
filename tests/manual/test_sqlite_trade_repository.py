"""
Botragram

Description:
    Manual SQLite trade repository smoke test.

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
from botragram.enums import OrderSide
from botragram.models import Trade
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteTradeRepository,
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
def _create_trade(
    *,
    trade_id: str,
    order_id: str,
    symbol: str,
    side: OrderSide,
    price: Decimal,
    quantity: Decimal,
    quote_quantity: Decimal,
    fee: Decimal,
    fee_asset: str,
    executed_at: datetime,
    realized_pnl: Decimal | None = None,
) -> Trade:
    """Create a trade for the SQLite smoke test."""
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        symbol=symbol,
        side=side,
        price=price,
        quantity=quantity,
        quote_quantity=quote_quantity,
        fee=fee,
        fee_asset=fee_asset,
        executed_at=executed_at,
        realized_pnl=realized_pnl,
    )


# =============================================================================
# Manual Test
# =============================================================================
async def _run_test() -> None:
    """Run the SQLite trade repository smoke test."""
    base_time = datetime(
        2026,
        8,
        6,
        16,
        0,
        tzinfo=timezone.utc,
    )

    trade_one = _create_trade(
        trade_id="2001",
        order_id="1001",
        symbol=_SYMBOL,
        side=OrderSide.BUY,
        price=Decimal("60000"),
        quantity=Decimal("0.01"),
        quote_quantity=Decimal("600"),
        fee=Decimal("0.60"),
        fee_asset="USDT",
        executed_at=base_time,
    )

    trade_two = _create_trade(
        trade_id="2002",
        order_id="1001",
        symbol=_SYMBOL,
        side=OrderSide.BUY,
        price=Decimal("60100"),
        quantity=Decimal("0.02"),
        quote_quantity=Decimal("1202"),
        fee=Decimal("1.202"),
        fee_asset="USDT",
        executed_at=base_time + timedelta(minutes=1),
    )

    trade_three = _create_trade(
        trade_id="2003",
        order_id="1002",
        symbol=_OTHER_SYMBOL,
        side=OrderSide.SELL,
        price=Decimal("3000"),
        quantity=Decimal("1"),
        quote_quantity=Decimal("3000"),
        fee=Decimal("3"),
        fee_asset="USDT",
        realized_pnl=Decimal("125"),
        executed_at=base_time + timedelta(minutes=2),
    )

    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "botragram_trade_test.db"

        async with SQLiteDatabase(
            database_path=database_path,
        ) as database:
            migration_manager = SQLiteMigrationManager(
                database=database,
            )

            schema_version = await migration_manager.initialize()

            assert schema_version == _EXPECTED_SCHEMA_VERSION

            repository = SQLiteTradeRepository(
                database=database,
            )

            await repository.save_many(
                trades=(
                    trade_one,
                    trade_two,
                    trade_three,
                ),
            )

            total_count = await repository.count()

            assert total_count == _EXPECTED_TOTAL_COUNT

            symbol_count = await repository.count(
                symbol=_SYMBOL,
            )

            assert symbol_count == 2

            buy_count = await repository.count(
                side=OrderSide.BUY,
            )

            assert buy_count == 2

            stored_trade = await repository.get_by_id(
                trade_id="2001",
                symbol=_SYMBOL,
            )

            assert stored_trade == trade_one

            stored_without_symbol = await repository.get_by_id(
                trade_id="2002",
            )

            assert stored_without_symbol == trade_two

            order_trades = await repository.get_by_order_id(
                order_id="1001",
                symbol=_SYMBOL,
            )

            assert order_trades == (
                trade_one,
                trade_two,
            )

            latest = await repository.get_latest(
                limit=1,
            )

            assert latest == (trade_three,)

            latest_for_symbol = await repository.get_latest(
                limit=1,
                symbol=_SYMBOL,
            )

            assert latest_for_symbol == (trade_two,)

            trades_between = await repository.get_between(
                start_time=base_time,
                end_time=base_time + timedelta(minutes=1),
                symbol=_SYMBOL,
            )

            assert trades_between == (
                trade_one,
                trade_two,
            )

            updated_trade = _create_trade(
                trade_id="2001",
                order_id="1001",
                symbol=_SYMBOL,
                side=OrderSide.BUY,
                price=Decimal("60050"),
                quantity=Decimal("0.01"),
                quote_quantity=Decimal("600.50"),
                fee=Decimal("0.6005"),
                fee_asset="BNB",
                realized_pnl=Decimal("0"),
                executed_at=base_time,
            )

            await repository.save(
                trade=updated_trade,
            )

            updated_result = await repository.get_by_id(
                trade_id="2001",
                symbol=_SYMBOL,
            )

            assert updated_result == updated_trade

            deleted_count = await repository.delete_before(
                before=base_time + timedelta(seconds=30),
                symbol=_SYMBOL,
            )

            assert deleted_count == 1

            remaining_count = await repository.count()

            assert remaining_count == 2

            print(
                "SQLite trade repository smoke test passed:",
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
