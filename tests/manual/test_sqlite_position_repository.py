"""
Botragram

Description:
    Manual SQLite position repository smoke test.

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
from botragram.enums import PositionSide
from botragram.models import Position
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLitePositionRepository,
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
def _create_position(
    *,
    symbol: str,
    side: PositionSide,
    quantity: Decimal,
    entry_price: Decimal,
    current_price: Decimal,
    unrealized_pnl: Decimal,
    leverage: int,
    opened_at: datetime,
    updated_at: datetime,
) -> Position:
    """Create a position for the SQLite smoke test."""
    return Position(
        symbol=symbol,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        current_price=current_price,
        unrealized_pnl=unrealized_pnl,
        leverage=leverage,
        opened_at=opened_at,
        updated_at=updated_at,
    )


# =============================================================================
# Manual Test
# =============================================================================
async def _run_test() -> None:
    """Run the SQLite position repository smoke test."""
    base_time = datetime(
        2026,
        8,
        6,
        17,
        0,
        tzinfo=timezone.utc,
    )

    position_one = _create_position(
        symbol=_SYMBOL,
        side=PositionSide.LONG,
        quantity=Decimal("0.10"),
        entry_price=Decimal("60000"),
        current_price=Decimal("61000"),
        unrealized_pnl=Decimal("100"),
        leverage=2,
        opened_at=base_time,
        updated_at=base_time,
    )

    position_two = _create_position(
        symbol=_OTHER_SYMBOL,
        side=PositionSide.SHORT,
        quantity=Decimal("1.5"),
        entry_price=Decimal("3000"),
        current_price=Decimal("2900"),
        unrealized_pnl=Decimal("150"),
        leverage=3,
        opened_at=base_time + timedelta(minutes=1),
        updated_at=base_time + timedelta(minutes=1),
    )

    closed_position = _create_position(
        symbol="SOLUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("0"),
        entry_price=Decimal("150"),
        current_price=Decimal("155"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=base_time + timedelta(minutes=2),
        updated_at=base_time + timedelta(minutes=2),
    )

    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "botragram_position_test.db"

        async with SQLiteDatabase(
            database_path=database_path,
        ) as database:
            migration_manager = SQLiteMigrationManager(
                database=database,
            )

            schema_version = await migration_manager.initialize()

            assert schema_version == _EXPECTED_SCHEMA_VERSION

            repository = SQLitePositionRepository(
                database=database,
            )

            await repository.save_many(
                positions=(
                    position_one,
                    position_two,
                    closed_position,
                ),
            )

            total_count = await repository.count()

            assert total_count == _EXPECTED_TOTAL_COUNT

            stored_position = await repository.get_by_symbol(
                symbol=_SYMBOL,
            )

            assert stored_position == position_one

            all_positions = await repository.get_all()

            assert all_positions == (
                position_one,
                position_two,
                closed_position,
            )

            long_positions = await repository.get_by_side(
                side=PositionSide.LONG,
            )

            assert long_positions == (
                position_one,
                closed_position,
            )

            short_positions = await repository.get_by_side(
                side=PositionSide.SHORT,
            )

            assert short_positions == (position_two,)

            open_positions = await repository.get_open_positions()

            assert open_positions == (
                position_one,
                position_two,
            )

            updated_position = _create_position(
                symbol=_SYMBOL,
                side=PositionSide.LONG,
                quantity=Decimal("0.10"),
                entry_price=Decimal("60000"),
                current_price=Decimal("62000"),
                unrealized_pnl=Decimal("200"),
                leverage=2,
                opened_at=base_time,
                updated_at=base_time + timedelta(minutes=5),
            )

            await repository.update(
                position=updated_position,
            )

            updated_result = await repository.get_by_symbol(
                symbol=_SYMBOL,
            )

            assert updated_result == updated_position

            missing_position = _create_position(
                symbol="BNBUSDT",
                side=PositionSide.LONG,
                quantity=Decimal("1"),
                entry_price=Decimal("500"),
                current_price=Decimal("510"),
                unrealized_pnl=Decimal("10"),
                leverage=1,
                opened_at=base_time,
                updated_at=base_time,
            )

            try:
                await repository.update(
                    position=missing_position,
                )
            except LookupError:
                pass
            else:
                raise AssertionError(
                    "Expected update of missing position to raise LookupError"
                )

            deleted = await repository.delete(
                symbol=_OTHER_SYMBOL,
            )

            assert deleted is True

            missing_deleted = await repository.delete(
                symbol="UNKNOWNUSDT",
            )

            assert missing_deleted is False

            remaining_count = await repository.count()

            assert remaining_count == 2

            deleted_all = await repository.delete_all()

            assert deleted_all == 2

            final_count = await repository.count()

            assert final_count == 0

            print(
                "SQLite position repository smoke test passed:",
                {
                    "schema_version": schema_version,
                    "total_inserted": total_count,
                    "remaining_before_clear": remaining_count,
                    "final_count": final_count,
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
