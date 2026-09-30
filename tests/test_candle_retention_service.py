"""
Botragram

Description:
    Automated candle retention service unit tests.

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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.models import Candle
from botragram.services import CandleRetentionService
from botragram.storage.memory import MemoryCandleRepository
from botragram.storage.sqlite import SQLiteDatabase

_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


@dataclass(slots=True)
class _RecordingOptimizer:
    calls: int = 0

    async def optimize_after_prune(self) -> None:
        self.calls += 1


def _make_candle(*, symbol: str, open_time: datetime) -> Candle:
    return Candle(
        symbol=symbol,
        interval=Interval.M15,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("99"),
        close_price=Decimal("102"),
        volume=Decimal("50"),
    )


def test_candle_retention_validation_rejects_non_positive() -> None:
    repository = MemoryCandleRepository()
    with pytest.raises(ValueError, match="Retention days"):
        CandleRetentionService(
            candle_repository=repository,
            retention_days=0,
        )
    with pytest.raises(ValueError, match="Pruning interval hours"):
        CandleRetentionService(
            candle_repository=repository,
            pruning_interval_hours=0,
        )


@pytest.mark.asyncio
async def test_prune_expired_candles_removes_only_older_than_retention() -> None:
    repository = MemoryCandleRepository()
    old_candle = _make_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(days=10),
    )
    fresh_candle = _make_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(days=2),
    )
    await repository.save_many(candles=[old_candle, fresh_candle])
    assert await repository.count() == 2

    service = CandleRetentionService(
        candle_repository=repository,
        retention_days=7,
        utc_now=lambda: _NOW,
    )

    deleted_count = await service.prune_expired_candles()
    assert deleted_count == 1
    assert await repository.count() == 1

    remaining = await repository.get_latest(
        symbol="BTCUSDT",
        interval=Interval.M15,
        limit=10,
    )
    assert len(remaining) == 1
    assert remaining[0].open_time == fresh_candle.open_time


@pytest.mark.asyncio
async def test_storage_optimization_runs_only_after_deleted_candles() -> None:
    repository = MemoryCandleRepository()
    optimizer = _RecordingOptimizer()
    service = CandleRetentionService(
        candle_repository=repository,
        database=optimizer,
        utc_now=lambda: _NOW,
    )
    assert await service.prune_expired_candles() == 0
    assert optimizer.calls == 0

    await repository.save(
        candle=_make_candle(symbol="BTCUSDT", open_time=_NOW - timedelta(days=10))
    )
    assert await service.prune_expired_candles() == 1
    assert optimizer.calls == 1


@pytest.mark.asyncio
async def test_sqlite_storage_optimization_contract() -> None:
    """The production SQLite adapter accepts the storage-neutral maintenance call."""
    database = SQLiteDatabase(database_path=":memory:")
    await database.connect()
    try:
        await database.optimize_after_prune()
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_candle_retention_service_start_stop() -> None:
    repository = MemoryCandleRepository()
    service = CandleRetentionService(
        candle_repository=repository,
        retention_days=7,
        pruning_interval_hours=1,
        utc_now=lambda: _NOW,
    )

    await service.start()
    assert service.is_running

    # Starting while already running is idempotent
    await service.start()

    await asyncio.sleep(0.01)
    await service.stop()
    assert not service.is_running
