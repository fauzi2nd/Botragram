"""
Botragram

Description:
    Unit tests for MarketService stream_resampled_candles.

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
from collections.abc import AsyncIterator
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

__all__ = ()


# =============================================================================
# Helpers
# =============================================================================
def _make_1m_candle(
    *,
    symbol: str = "BTCUSDT",
    open_time: datetime,
    open_price: str = "100",
    high_price: str = "105",
    low_price: str = "95",
    close_price: str = "102",
    volume: str = "1.0",
) -> Candle:
    return Candle(
        symbol=symbol,
        interval=Interval.M1,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open_price=Decimal(open_price),
        high_price=Decimal(high_price),
        low_price=Decimal(low_price),
        close_price=Decimal(close_price),
        volume=Decimal(volume),
    )


async def _setup_sqlite_repo() -> tuple[SQLiteDatabase, SQLiteCandleRepository]:
    database = SQLiteDatabase(database_path=":memory:")
    await database.connect()
    await SQLiteMigrationManager(database=database).initialize()
    return database, SQLiteCandleRepository(database=database)


class _MockStreamClient(BaseStreamClient):
    """Stub stream client yielding pre-defined candles."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        pass

    async def stream_ticker(self, *, symbol: str):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def stream_candles(
        self, *, symbol: str, interval: Interval
    ) -> AsyncIterator[Candle]:
        for c in self._candles:
            yield c

    async def unsubscribe(self, *, symbol: str) -> None:
        pass

    async def close(self) -> None:
        self._connected = False


# =============================================================================
# Tests
# =============================================================================
@pytest.mark.asyncio
async def test_stream_resampled_candles_closed_only() -> None:
    """Stream resampled candles in closed-only mode yields completed 5m candles."""
    db, sqlite_repo = await _setup_sqlite_repo()
    try:
        base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        # 11 source 1m candles (minute 0 through minute 10)
        # minute 0-4 => bucket 10:00 (closed by minute 5)
        # minute 5-9 => bucket 10:05 (closed by minute 10)
        # minute 10 => starts bucket 10:10 (in-flight, not closed)
        source_candles = [
            _make_1m_candle(
                open_time=base_time + timedelta(minutes=i),
                open_price=f"{100 + i}",
                high_price=f"{105 + i}",
                low_price=f"{95 + i}",
                close_price=f"{102 + i}",
                volume="2.0",
            )
            for i in range(11)
        ]

        stream_client = _MockStreamClient(candles=source_candles)
        exchange_mock = MagicMock(spec=BaseExchangeClient)

        service = MarketService(
            exchange_client=exchange_mock,
            stream_client=stream_client,
            candle_repository=sqlite_repo,
        )

        emitted: list[Candle] = []
        async for c in service.stream_resampled_candles(
            symbol="BTCUSDT",
            target_interval=Interval.M5,
            source_interval=Interval.M1,
            persist_source=True,
            closed_only=True,
        ):
            emitted.append(c)

        # Expect exactly 2 closed 5m candles
        assert len(emitted) == 2

        c0 = emitted[0]
        assert c0.open_time == base_time
        assert c0.close_time == base_time + timedelta(minutes=5)
        assert c0.interval == Interval.M5
        assert c0.open_price == Decimal("100")
        assert c0.high_price == Decimal("109")  # max(105+4)
        assert c0.low_price == Decimal("95")  # min(95+0)
        assert c0.close_price == Decimal("106")  # close of min 4: 102+4
        assert c0.volume == Decimal("10.0")  # 5 * 2.0

        c1 = emitted[1]
        assert c1.open_time == base_time + timedelta(minutes=5)
        assert c1.close_time == base_time + timedelta(minutes=10)
        assert c1.interval == Interval.M5
        assert c1.open_price == Decimal("105")
        assert c1.high_price == Decimal("114")  # max(105+9)
        assert c1.low_price == Decimal("100")  # min(95+5)
        assert c1.close_price == Decimal("111")  # close of min 9: 102+9
        assert c1.volume == Decimal("10.0")

        # Verify all 11 source 1m candles were persisted to SQLite
        stored_1m = await sqlite_repo.get_latest(
            symbol="BTCUSDT",
            interval=Interval.M1,
            limit=50,
        )
        assert len(stored_1m) == 11

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_stream_resampled_candles_forming_mode() -> None:
    """Stream resampled candles with closed_only=False yields forming candle."""
    db, sqlite_repo = await _setup_sqlite_repo()
    try:
        base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        source_candles = [
            _make_1m_candle(
                open_time=base_time + timedelta(minutes=i),
                close_price=f"{100 + i}",
                volume="1.0",
            )
            for i in range(3)
        ]

        stream_client = _MockStreamClient(candles=source_candles)
        exchange_mock = MagicMock(spec=BaseExchangeClient)

        service = MarketService(
            exchange_client=exchange_mock,
            stream_client=stream_client,
            candle_repository=sqlite_repo,
        )

        emitted: list[Candle] = []
        async for c in service.stream_resampled_candles(
            symbol="BTCUSDT",
            target_interval=Interval.M5,
            closed_only=False,
            persist_source=False,
        ):
            emitted.append(c)

        # 3 ticks yielded
        assert len(emitted) == 3
        assert emitted[0].volume == Decimal("1.0")
        assert emitted[1].volume == Decimal("2.0")
        assert emitted[2].volume == Decimal("3.0")
        assert emitted[2].close_price == Decimal("102")

        # Repository should have 0 stored candles because persist_source=False
        stored = await sqlite_repo.get_latest(
            symbol="BTCUSDT",
            interval=Interval.M1,
            limit=10,
        )
        assert len(stored) == 0

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_stream_resampled_candles_same_interval_passthrough() -> None:
    """When target_interval is source_interval, delegates to stream_candles."""
    db, sqlite_repo = await _setup_sqlite_repo()
    try:
        base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        source_candles = [
            _make_1m_candle(open_time=base_time + timedelta(minutes=i))
            for i in range(2)
        ]

        stream_client = _MockStreamClient(candles=source_candles)
        exchange_mock = MagicMock(spec=BaseExchangeClient)

        service = MarketService(
            exchange_client=exchange_mock,
            stream_client=stream_client,
            candle_repository=sqlite_repo,
        )

        emitted: list[Candle] = []
        async for c in service.stream_resampled_candles(
            symbol="BTCUSDT",
            target_interval=Interval.M1,
            source_interval=Interval.M1,
            persist_source=True,
        ):
            emitted.append(c)

        assert len(emitted) == 2
        assert emitted[0].interval == Interval.M1

    finally:
        await db.close()
