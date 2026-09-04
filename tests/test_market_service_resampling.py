"""
Botragram

Description:
    Unit tests for MarketService stored candle resampling integration.

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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.exchanges.base import BaseExchangeClient, BaseStreamClient
from botragram.models import Candle
from botragram.services.market_service import MarketService
from botragram.storage.sqlite import (
    SQLiteCandleRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
)


# =============================================================================
# Helper Fixtures / Builders
# =============================================================================
def _make_1m_candle(
    *,
    symbol: str = "BTCUSDT",
    open_time: datetime,
    close_price: str,
    volume: str = "1.0",
) -> Candle:
    return Candle(
        symbol=symbol,
        interval=Interval.M1,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("95"),
        close_price=Decimal(close_price),
        volume=Decimal(volume),
    )


async def _setup_sqlite_repo() -> tuple[SQLiteDatabase, SQLiteCandleRepository]:
    database = SQLiteDatabase(database_path=":memory:")
    await database.connect()
    await SQLiteMigrationManager(database=database).initialize()
    return database, SQLiteCandleRepository(database=database)


# =============================================================================
# Tests
# =============================================================================
@pytest.mark.asyncio
async def test_get_stored_resampled_candles() -> None:
    """MarketService resamples stored 1m candles into 5m on-the-fly."""
    db, sqlite_repo = await _setup_sqlite_repo()
    try:
        base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        # Store 15 continuous 1m candles (3 full 5m candles: 10:00, 10:05, 10:10)
        candles = [
            _make_1m_candle(
                open_time=base_time + timedelta(minutes=i),
                close_price=f"{100 + i}",
                volume="2.0",
            )
            for i in range(15)
        ]
        await sqlite_repo.save_many(candles=candles)

        exchange_mock = MagicMock(spec=BaseExchangeClient)
        stream_mock = MagicMock(spec=BaseStreamClient)

        market_service = MarketService(
            exchange_client=exchange_mock,
            stream_client=stream_mock,
            candle_repository=sqlite_repo,
        )

        # Request 2 5m candles
        resampled = await market_service.get_stored_resampled_candles(
            symbol="BTCUSDT",
            target_interval=Interval.M5,
            limit=2,
        )

        assert len(resampled) == 2
        # Should be the latest 2: 10:05 and 10:10
        assert resampled[0].open_time == base_time + timedelta(minutes=5)
        assert resampled[0].interval == Interval.M5
        assert resampled[0].volume == Decimal("10.0")

        assert resampled[1].open_time == base_time + timedelta(minutes=10)
        assert resampled[1].interval == Interval.M5
        assert resampled[1].volume == Decimal("10.0")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_stored_resampled_candles_between() -> None:
    """MarketService resamples stored 1m candles over an explicit datetime range."""
    db, sqlite_repo = await _setup_sqlite_repo()
    try:
        base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        candles = [
            _make_1m_candle(
                open_time=base_time + timedelta(minutes=i),
                close_price=f"{100 + i}",
                volume="1.5",
            )
            for i in range(30)
        ]
        await sqlite_repo.save_many(candles=candles)

        exchange_mock = MagicMock(spec=BaseExchangeClient)
        stream_mock = MagicMock(spec=BaseStreamClient)

        market_service = MarketService(
            exchange_client=exchange_mock,
            stream_client=stream_mock,
            candle_repository=sqlite_repo,
        )

        # Query range corresponding to 10:00 to 10:14 (first 15 minutes = 1 15m candle)
        resampled = await market_service.get_stored_resampled_candles_between(
            symbol="BTCUSDT",
            target_interval=Interval.M15,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=14),
        )

        assert len(resampled) == 1
        assert resampled[0].interval == Interval.M15
        assert resampled[0].open_time == base_time
        assert resampled[0].close_time == base_time + timedelta(minutes=15)
        assert resampled[0].volume == Decimal("22.5")
    finally:
        await db.close()
