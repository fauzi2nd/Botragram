"""
Botragram

Description:
    Unit and regression tests for Phase 4: Runtime State Persistence and CFD Gates.

Python:
    3.14+
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from botragram.enums import (
    ExchangeType,
    ExecutionPolicy,
    MarketType,
    OrderType,
)
from botragram.services.live_futures_entry_service import LiveFuturesEntryService
from botragram.storage.memory import MemoryRuntimeSettingsRepository
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteRuntimeSettingsRepository,
)


@pytest.mark.asyncio
async def test_memory_runtime_settings_repository_roundtrip() -> None:
    """Verify in-memory repository stores and retrieves new settings."""
    repo = MemoryRuntimeSettingsRepository()

    assert await repo.get_market_type() is None
    await repo.save_market_type(market_type=MarketType.CFD)
    assert await repo.get_market_type() is MarketType.CFD

    assert await repo.get_exchange() is None
    await repo.save_exchange(exchange_type=ExchangeType.BITGET)
    assert await repo.get_exchange() is ExchangeType.BITGET

    assert await repo.get_execution_policy() is None
    await repo.save_execution_policy(execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE)
    assert await repo.get_execution_policy() is ExecutionPolicy.AUTONOMOUS_LIVE


@pytest.mark.asyncio
async def test_sqlite_runtime_settings_repository_roundtrip() -> None:
    """Verify SQLite repository stores and retrieves settings with table schema."""
    with TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_settings.db"
        db = SQLiteDatabase(database_path=db_path)
        await db.connect()
        try:
            # Create runtime_settings table
            async with db.transaction() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runtime_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )

            repo = SQLiteRuntimeSettingsRepository(database=db)

            # Initially empty
            assert await repo.get_market_type() is None
            assert await repo.get_exchange() is None
            assert await repo.get_execution_policy() is None

            # Save and retrieve MarketType
            await repo.save_market_type(market_type=MarketType.CFD)
            assert await repo.get_market_type() is MarketType.CFD

            # Save and retrieve ExchangeType
            await repo.save_exchange(exchange_type=ExchangeType.BITGET)
            assert await repo.get_exchange() is ExchangeType.BITGET

            # Save and retrieve ExecutionPolicy
            await repo.save_execution_policy(
                execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE
            )
            assert await repo.get_execution_policy() is ExecutionPolicy.AUTONOMOUS_LIVE

            # Update existing
            await repo.save_market_type(market_type=MarketType.FUTURES)
            assert await repo.get_market_type() is MarketType.FUTURES
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_sqlite_runtime_settings_safe_when_no_table() -> None:
    """Verify SQLite repository gracefully returns None when table is missing."""
    with TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "empty.db"
        db = SQLiteDatabase(database_path=db_path)
        await db.connect()
        try:
            repo = SQLiteRuntimeSettingsRepository(database=db)
            assert await repo.get_market_type() is None
            assert await repo.get_exchange() is None
            assert await repo.get_execution_policy() is None
            assert await repo.get_strategy() is None
        finally:
            await db.close()


def test_live_futures_entry_validate_entry_allows_cfd() -> None:
    """Verify _validate_entry accepts MarketType.CFD alongside MarketType.FUTURES."""
    # MarketType.CFD
    service_cfd = object.__new__(LiveFuturesEntryService)
    object.__setattr__(service_cfd, "market_type", MarketType.CFD)
    validate_fn = getattr(service_cfd, "_validate_entry")
    # Should not raise
    validate_fn(order_type=OrderType.MARKET)

    # MarketType.FUTURES
    service_fut = object.__new__(LiveFuturesEntryService)
    object.__setattr__(service_fut, "market_type", MarketType.FUTURES)
    validate_fn_fut = getattr(service_fut, "_validate_entry")
    # Should not raise
    validate_fn_fut(order_type=OrderType.MARKET)

    # MarketType.SPOT
    service_spot = object.__new__(LiveFuturesEntryService)
    object.__setattr__(service_spot, "market_type", MarketType.SPOT)
    validate_fn_spot = getattr(service_spot, "_validate_entry")
    with pytest.raises(RuntimeError, match="requires FUTURES or CFD"):
        validate_fn_spot(order_type=OrderType.MARKET)
