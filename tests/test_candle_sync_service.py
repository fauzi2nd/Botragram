"""
Botragram

Description:
    Unit tests for CandleSyncService.

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
from botragram.models import Candle, MarketUniverseEntry
from botragram.services.candle_sync_service import CandleSyncService
from botragram.services.market_service import MarketService
from botragram.storage.sqlite import (
    SQLiteCandleRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
)

__all__ = ()


# =============================================================================
# Helper Fixtures
# =============================================================================
def _make_1m_candle(
    *,
    symbol: str = "BTCUSDT",
    open_time: datetime,
) -> Candle:
    return Candle(
        symbol=symbol,
        interval=Interval.M1,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("95"),
        close_price=Decimal("102"),
        volume=Decimal("1.0"),
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
async def test_check_symbol_gap_empty_repository() -> None:
    """When no candles exist for a symbol, gap returns None last close and 0 bars."""
    db, repo = await _setup_sqlite_repo()
    try:
        mock_market = MagicMock(spec=MarketService)
        service = CandleSyncService(
            market_service=mock_market,
            candle_repository=repo,
        )

        last_close, now, missing_bars = await service.check_symbol_gap(symbol="BTCUSDT")
        assert last_close is None
        assert missing_bars == 0
        assert now.tzinfo is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_check_symbol_gap_with_lagging_candle() -> None:
    """When candle closed 10 minutes ago, returns gap of 10 missing bars."""
    db, repo = await _setup_sqlite_repo()
    try:
        now = datetime.now(timezone.utc)
        ten_mins_ago = now - timedelta(minutes=10)
        c = _make_1m_candle(open_time=ten_mins_ago - timedelta(minutes=1))
        await repo.save(candle=c)

        mock_market = MagicMock(spec=MarketService)
        service = CandleSyncService(
            market_service=mock_market,
            candle_repository=repo,
        )

        last_close, _, missing_bars = await service.check_symbol_gap(symbol="BTCUSDT")
        assert last_close is not None
        assert 9 <= missing_bars <= 11
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_sync_symbol_fetches_and_persists() -> None:
    """sync_symbol calls market_service.get_candles and persists missing data."""
    db, repo = await _setup_sqlite_repo()
    try:
        exchange_mock = MagicMock(spec=BaseExchangeClient)
        stream_mock = MagicMock(spec=BaseStreamClient)

        base_time = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        mock_candles = [
            _make_1m_candle(open_time=base_time + timedelta(minutes=i))
            for i in range(5)
        ]
        exchange_mock.get_candles = AsyncMock(return_value=mock_candles)

        market_service = MarketService(
            exchange_client=exchange_mock,
            stream_client=stream_mock,
            candle_repository=repo,
        )
        sync_service = CandleSyncService(
            market_service=market_service,
            candle_repository=repo,
        )

        count = await sync_service.sync_symbol(
            symbol="BTCUSDT",
            start_time=base_time,
            end_time=base_time + timedelta(minutes=5),
        )

        assert count == 5
        stored = await repo.get_latest(symbol="BTCUSDT", interval=Interval.M1, limit=10)
        assert len(stored) == 5
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_sync_symbols_concurrent() -> None:
    """sync_symbols concurrently processes multiple symbols."""
    db, repo = await _setup_sqlite_repo()
    try:
        exchange_mock = MagicMock(spec=BaseExchangeClient)
        stream_mock = MagicMock(spec=BaseStreamClient)

        base_time = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)

        async def _mock_get_candles(
            *,
            symbol: str,
            interval: Interval,
            limit: int,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
        ) -> list[Candle]:
            return [
                _make_1m_candle(
                    symbol=symbol, open_time=base_time + timedelta(minutes=i)
                )
                for i in range(3)
            ]

        exchange_mock.get_candles = AsyncMock(side_effect=_mock_get_candles)

        market_service = MarketService(
            exchange_client=exchange_mock,
            stream_client=stream_mock,
            candle_repository=repo,
        )
        sync_service = CandleSyncService(
            market_service=market_service,
            candle_repository=repo,
        )

        result = await sync_service.sync_symbols(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            start_time=base_time,
            concurrency=2,
        )

        assert result["BTCUSDT"] == 3
        assert result["ETHUSDT"] == 3
        assert result["SOLUSDT"] == 3
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_run_periodic_sync_stops_gracefully() -> None:
    """run_periodic_sync runs and terminates when stop_event is set."""
    db, repo = await _setup_sqlite_repo()
    try:
        mock_market = MagicMock(spec=MarketService)
        service = CandleSyncService(
            market_service=mock_market,
            candle_repository=repo,
        )

        stop_event = asyncio.Event()

        async def _symbols_provider() -> list[str]:
            stop_event.set()
            return []

        await service.run_periodic_sync(
            symbols_provider=_symbols_provider,
            interval_seconds=1,
            stop_event=stop_event,
        )

        assert stop_event.is_set()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_run_adaptive_background_sync_adapts_and_stops() -> None:
    """run_adaptive_background_sync queries trading symbols and adapts delay."""
    db, repo = await _setup_sqlite_repo()
    try:
        mock_market = MagicMock(spec=MarketService)
        mock_market.get_trading_symbols = AsyncMock(return_value=("BTCUSDT", "ETHUSDT"))
        service = CandleSyncService(
            market_service=mock_market,
            candle_repository=repo,
        )

        stop_event = asyncio.Event()
        checked_full = False

        async def _mock_is_full() -> bool:
            nonlocal checked_full
            checked_full = True
            stop_event.set()
            return True

        await service.run_adaptive_background_sync(
            quote_asset="USDT",
            is_positions_full_provider=_mock_is_full,
            stop_event=stop_event,
            batch_size=2,
            normal_delay_seconds=0.1,
            full_delay_seconds=0.01,
        )

        assert stop_event.is_set()
        assert checked_full is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_ranked_symbols_prioritizes_volume_universe() -> None:
    """_get_ranked_symbols orders top 24h volume symbols first and appends remaining."""
    db, repo = await _setup_sqlite_repo()
    try:
        mock_market = MagicMock(spec=MarketService)
        mock_market.get_market_universe = AsyncMock(
            return_value=(
                MarketUniverseEntry(symbol="SOLUSDT", quote_volume=Decimal("5000000")),
                MarketUniverseEntry(symbol="BTCUSDT", quote_volume=Decimal("4000000")),
            )
        )
        mock_market.get_trading_symbols = AsyncMock(
            return_value=("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
        )
        service = CandleSyncService(
            market_service=mock_market,
            candle_repository=repo,
        )

        ranked = await service.get_ranked_symbols(quote_asset="USDT")

        # SOLUSDT and BTCUSDT from universe must be first, followed by others
        assert ranked == ("SOLUSDT", "BTCUSDT", "ETHUSDT", "XRPUSDT")
    finally:
        await db.close()
