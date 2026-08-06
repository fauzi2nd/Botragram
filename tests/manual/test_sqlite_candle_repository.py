"""
Botragram

Description:
    Manual SQLite candle repository smoke test.

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
from botragram.enums import Interval
from botragram.models import Candle
from botragram.storage.sqlite import (
    SQLiteCandleRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
)

# =============================================================================
# Constants
# =============================================================================
_SYMBOL = "BTCUSDT"
_INTERVAL = Interval("1m")
_OTHER_INTERVAL = Interval("5m")

_EXPECTED_SCHEMA_VERSION = 1
_EXPECTED_TOTAL_COUNT = 3


# =============================================================================
# Test Helpers
# =============================================================================
def _create_candle(
    *,
    interval: Interval,
    open_time: datetime,
    close_price: Decimal,
) -> Candle:
    """Create a candle for the SQLite smoke test."""
    return Candle(
        symbol=_SYMBOL,
        interval=interval,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1) - timedelta(milliseconds=1),
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=close_price,
        volume=Decimal("15.5"),
    )


# =============================================================================
# Manual Test
# =============================================================================
async def _run_test() -> None:
    """Run the SQLite candle repository smoke test."""
    base_time = datetime(
        2026,
        8,
        6,
        12,
        0,
        tzinfo=timezone.utc,
    )

    candle_one = _create_candle(
        interval=_INTERVAL,
        open_time=base_time,
        close_price=Decimal("101"),
    )
    candle_two = _create_candle(
        interval=_INTERVAL,
        open_time=base_time + timedelta(minutes=1),
        close_price=Decimal("102"),
    )
    other_interval_candle = _create_candle(
        interval=_OTHER_INTERVAL,
        open_time=base_time,
        close_price=Decimal("105"),
    )

    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "botragram_test.db"

        async with SQLiteDatabase(
            database_path=database_path,
        ) as database:
            migration_manager = SQLiteMigrationManager(
                database=database,
            )

            schema_version = await migration_manager.initialize()

            assert schema_version == _EXPECTED_SCHEMA_VERSION

            repository = SQLiteCandleRepository(
                database=database,
            )

            await repository.save_many(
                candles=(
                    candle_one,
                    candle_two,
                    other_interval_candle,
                ),
            )

            total_count = await repository.count()

            assert total_count == _EXPECTED_TOTAL_COUNT

            one_minute_count = await repository.count(
                symbol=_SYMBOL,
                interval=_INTERVAL,
            )

            assert one_minute_count == 2

            five_minute_count = await repository.count(
                symbol=_SYMBOL,
                interval=_OTHER_INTERVAL,
            )

            assert five_minute_count == 1

            latest = await repository.get_latest(
                symbol=_SYMBOL,
                interval=_INTERVAL,
                limit=1,
            )

            assert latest == (candle_two,)

            stored_candle = await repository.get_by_open_time(
                symbol=_SYMBOL,
                interval=_INTERVAL,
                open_time=base_time,
            )

            assert stored_candle == candle_one

            candles_between = await repository.get_between(
                symbol=_SYMBOL,
                interval=_INTERVAL,
                start_time=base_time,
                end_time=base_time + timedelta(minutes=1),
            )

            assert candles_between == (
                candle_one,
                candle_two,
            )

            updated_candle = _create_candle(
                interval=_INTERVAL,
                open_time=base_time,
                close_price=Decimal("109"),
            )

            await repository.save(
                candle=updated_candle,
            )

            updated_result = await repository.get_by_open_time(
                symbol=_SYMBOL,
                interval=_INTERVAL,
                open_time=base_time,
            )

            assert updated_result == updated_candle

            deleted_count = await repository.delete_before(
                before=base_time + timedelta(seconds=30),
                symbol=_SYMBOL,
                interval=_INTERVAL,
            )

            assert deleted_count == 1

            remaining_count = await repository.count()

            assert remaining_count == 2

            print(
                "SQLite candle repository smoke test passed:",
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
