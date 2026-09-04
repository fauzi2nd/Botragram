"""
Botragram

Description:
    Unit tests for MarketService hybrid candle resolution (prefer_stored).

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
from unittest.mock import AsyncMock, MagicMock

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

__all__: list[str] = []


# =============================================================================
# Helper Fixtures / Builders
# =============================================================================
def _make_candle(
    *,
    symbol: str = "BTCUSDT",
    interval: Interval = Interval.M1,
    open_time: datetime,
    close_price: str = "100.0",
    volume: str = "1.0",
) -> Candle:
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=open_time,
        close_time=open_time + timedelta(seconds=interval.seconds),
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
async def test_get_candles_prefer_stored_returns_stored_when_fresh() -> None:
    """When stored candles are fresh, return them without calling exchange."""
    db, sqlite_repo = await _setup_sqlite_repo()
    try:
        base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        stored_candles = [
            _make_candle(
                open_time=base_time + timedelta(minutes=i),
                close_price=f"{100 + i}",
            )
            for i in range(10)
        ]
        await sqlite_repo.save_many(candles=stored_candles)

        mock_exchange = MagicMock(spec=BaseExchangeClient)
        mock_exchange.get_candles = AsyncMock()
        mock_stream = MagicMock(spec=BaseStreamClient)

        service = MarketService(
            exchange_client=mock_exchange,
            stream_client=mock_stream,
            candle_repository=sqlite_repo,
        )

        # as_of is 10:10:30 (latest candle closed at 10:10:00, next close is 10:11:00)
        as_of = datetime(2026, 9, 1, 10, 10, 30, tzinfo=timezone.utc)

        result = await service.get_candles(
            symbol="BTCUSDT",
            interval=Interval.M1,
            limit=10,
            prefer_stored=True,
            as_of=as_of,
        )

        assert len(result) == 10
        assert result[-1].open_time == base_time + timedelta(minutes=9)
        mock_exchange.get_candles.assert_not_called()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_candles_prefer_stored_falls_back_when_stale() -> None:
    """When stored candles are stale, fallback to exchange and persist new."""
    db, sqlite_repo = await _setup_sqlite_repo()
    try:
        base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        stored_candles = [
            _make_candle(
                open_time=base_time + timedelta(minutes=i),
                close_price=f"{100 + i}",
            )
            for i in range(5)
        ]
        await sqlite_repo.save_many(candles=stored_candles)

        fresh_time = datetime(2026, 9, 1, 10, 20, tzinfo=timezone.utc)
        exchange_candles = [
            _make_candle(
                open_time=fresh_time + timedelta(minutes=i),
                close_price=f"{200 + i}",
            )
            for i in range(5)
        ]

        mock_exchange = MagicMock(spec=BaseExchangeClient)
        mock_exchange.get_candles = AsyncMock(return_value=exchange_candles)
        mock_stream = MagicMock(spec=BaseStreamClient)

        service = MarketService(
            exchange_client=mock_exchange,
            stream_client=mock_stream,
            candle_repository=sqlite_repo,
        )

        # as_of is 10:25:00, whereas stored latest closed at 10:05:00 (stale)
        as_of = datetime(2026, 9, 1, 10, 25, 0, tzinfo=timezone.utc)

        result = await service.get_candles(
            symbol="BTCUSDT",
            interval=Interval.M1,
            limit=5,
            prefer_stored=True,
            as_of=as_of,
            persist=True,
        )

        assert len(result) == 5
        assert result[0].close_price == Decimal("200")
        mock_exchange.get_candles.assert_called_once()

        # Check that new candles were persisted
        stored_after = await sqlite_repo.get_latest(
            symbol="BTCUSDT",
            interval=Interval.M1,
            limit=5,
        )
        assert stored_after[-1].open_time == fresh_time + timedelta(minutes=4)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_candles_prefer_stored_with_resampling() -> None:
    """When target interval is M5 and M1 is in DB, resample without calling exchange."""
    db, sqlite_repo = await _setup_sqlite_repo()
    try:
        base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        # 15 minutes of M1 = 3 complete M5 candles (10:00, 10:05, 10:10)
        stored_candles = [
            _make_candle(
                open_time=base_time + timedelta(minutes=i),
                close_price=f"{100 + i}",
            )
            for i in range(15)
        ]
        await sqlite_repo.save_many(candles=stored_candles)

        mock_exchange = MagicMock(spec=BaseExchangeClient)
        mock_exchange.get_candles = AsyncMock()
        mock_stream = MagicMock(spec=BaseStreamClient)

        service = MarketService(
            exchange_client=mock_exchange,
            stream_client=mock_stream,
            candle_repository=sqlite_repo,
        )

        # as_of is 10:17:00 (latest M5 closed at 10:15:00, next M5 close is 10:20:00)
        as_of = datetime(2026, 9, 1, 10, 17, 0, tzinfo=timezone.utc)

        result = await service.get_candles(
            symbol="BTCUSDT",
            interval=Interval.M5,
            limit=3,
            prefer_stored=True,
            as_of=as_of,
        )

        assert len(result) == 3
        assert result[0].interval is Interval.M5
        assert result[-1].open_time == datetime(2026, 9, 1, 10, 10, tzinfo=timezone.utc)
        assert result[-1].close_time == datetime(
            2026, 9, 1, 10, 15, tzinfo=timezone.utc
        )
        mock_exchange.get_candles.assert_not_called()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_candles_prefer_stored_false_calls_exchange() -> None:
    """When prefer_stored=False (default), always call exchange."""
    db, sqlite_repo = await _setup_sqlite_repo()
    try:
        mock_candles = [_make_candle(open_time=datetime.now(timezone.utc))]
        mock_exchange = MagicMock(spec=BaseExchangeClient)
        mock_exchange.get_candles = AsyncMock(return_value=mock_candles)
        mock_stream = MagicMock(spec=BaseStreamClient)

        service = MarketService(
            exchange_client=mock_exchange,
            stream_client=mock_stream,
            candle_repository=sqlite_repo,
        )

        result = await service.get_candles(
            symbol="BTCUSDT",
            interval=Interval.M1,
            limit=1,
            persist=False,
        )

        assert result == mock_candles
        mock_exchange.get_candles.assert_called_once()
    finally:
        await db.close()
