"""
Botragram

Description:
    Manual SQLite signal repository smoke test.

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
from botragram.enums import SignalType
from botragram.models import Signal
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteSignalRepository,
)

# =============================================================================
# Constants
# =============================================================================
_SYMBOL = "BTCUSDT"
_OTHER_SYMBOL = "ETHUSDT"

_STRATEGY_NAME = "EMA_CROSS"
_OTHER_STRATEGY_NAME = "SUPERTREND"

_EXPECTED_SCHEMA_VERSION = 8
_EXPECTED_TOTAL_COUNT = 3


# =============================================================================
# Test Helpers
# =============================================================================
def _create_signal(
    *,
    symbol: str,
    strategy_name: str,
    generated_at: datetime,
    signal_type: SignalType,
    price: Decimal,
    confidence: Decimal,
    reason: str | None,
) -> Signal:
    """Create a signal for the SQLite smoke test."""
    return Signal(
        symbol=symbol,
        strategy_name=strategy_name,
        generated_at=generated_at,
        signal_type=signal_type,
        price=price,
        confidence=confidence,
        reason=reason,
    )


# =============================================================================
# Manual Test
# =============================================================================
async def _run_test() -> None:
    """Run the SQLite signal repository smoke test."""
    base_time = datetime(
        2026,
        8,
        6,
        13,
        0,
        tzinfo=timezone.utc,
    )

    signal_one = _create_signal(
        symbol=_SYMBOL,
        strategy_name=_STRATEGY_NAME,
        generated_at=base_time,
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.75"),
        reason="Bullish EMA crossover",
    )
    signal_two = _create_signal(
        symbol=_SYMBOL,
        strategy_name=_STRATEGY_NAME,
        generated_at=base_time + timedelta(minutes=1),
        signal_type=SignalType.HOLD,
        price=Decimal("101"),
        confidence=Decimal("0"),
        reason=None,
    )
    signal_three = _create_signal(
        symbol=_OTHER_SYMBOL,
        strategy_name=_OTHER_STRATEGY_NAME,
        generated_at=base_time + timedelta(minutes=2),
        signal_type=SignalType.SELL,
        price=Decimal("200"),
        confidence=Decimal("0.80"),
        reason="Supertrend reversal",
    )

    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "botragram_signal_test.db"

        async with SQLiteDatabase(
            database_path=database_path,
        ) as database:
            migration_manager = SQLiteMigrationManager(
                database=database,
            )

            schema_version = await migration_manager.initialize()

            assert schema_version == _EXPECTED_SCHEMA_VERSION

            repository = SQLiteSignalRepository(
                database=database,
            )

            await repository.save_many(
                signals=(
                    signal_one,
                    signal_two,
                    signal_three,
                ),
            )

            total_count = await repository.count()

            assert total_count == _EXPECTED_TOTAL_COUNT

            symbol_count = await repository.count(
                symbol=_SYMBOL,
            )

            assert symbol_count == 2

            buy_count = await repository.count(
                signal_type=SignalType.BUY,
            )

            assert buy_count == 1

            strategy_count = await repository.count(
                strategy_name=_STRATEGY_NAME,
            )

            assert strategy_count == 2

            latest = await repository.get_latest(
                limit=1,
                symbol=_SYMBOL,
            )

            assert latest == (signal_two,)

            latest_for_symbol = await repository.get_latest_for_symbol(
                symbol=_SYMBOL,
            )

            assert latest_for_symbol == signal_two

            latest_for_strategy = await repository.get_latest_for_symbol(
                symbol=_SYMBOL,
                strategy_name=_STRATEGY_NAME,
            )

            assert latest_for_strategy == signal_two

            signals_between = await repository.get_between(
                start_time=base_time,
                end_time=base_time + timedelta(minutes=1),
                symbol=_SYMBOL,
            )

            assert signals_between == (
                signal_one,
                signal_two,
            )

            updated_signal = _create_signal(
                symbol=_SYMBOL,
                strategy_name=_STRATEGY_NAME,
                generated_at=base_time,
                signal_type=SignalType.BUY,
                price=Decimal("102"),
                confidence=Decimal("0.90"),
                reason="Updated bullish signal",
            )

            await repository.save(
                signal=updated_signal,
            )

            updated_result = await repository.get_between(
                start_time=base_time,
                end_time=base_time,
                symbol=_SYMBOL,
                strategy_name=_STRATEGY_NAME,
            )

            assert updated_result == (updated_signal,)

            deleted_count = await repository.delete_before(
                before=base_time + timedelta(seconds=30),
                symbol=_SYMBOL,
            )

            assert deleted_count == 1

            remaining_count = await repository.count()

            assert remaining_count == 2

            print(
                "SQLite signal repository smoke test passed:",
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
