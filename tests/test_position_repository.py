"""Durable position protection-identity repository tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from botragram.enums import Interval, PositionSide, StrategyType
from botragram.models import Position
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLitePositionRepository,
)

_NOW = datetime(2026, 8, 18, tzinfo=UTC)
_STOP_LOSS_CLIENT_ALGO_ID = "bsl-00000000000000000000000000000000"
_TAKE_PROFIT_CLIENT_ALGO_ID = "btp-00000000000000000000000000000000"


def _position() -> Position:
    """Build one position with distinct durable protection-leg identities."""
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("0.01"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss_client_algo_id=_STOP_LOSS_CLIENT_ALGO_ID,
        take_profit_client_algo_id=_TAKE_PROFIT_CLIENT_ALGO_ID,
    )


def test_sqlite_position_round_trip_preserves_protection_leg_identities() -> None:
    """Persist and restore the independent STOP and TP client identities."""
    asyncio.run(_run_sqlite_position_identity_test())


def test_position_rejects_shared_protection_leg_identity() -> None:
    """Prevent STOP and TP from using the same durable client identity."""
    with pytest.raises(ValueError, match="must be distinct"):
        replace(
            _position(),
            take_profit_client_algo_id=_STOP_LOSS_CLIENT_ALGO_ID,
        )


async def _run_sqlite_position_identity_test() -> None:
    """Exercise the positions migration and durable field mapping."""
    with TemporaryDirectory() as temporary_directory:
        database = SQLiteDatabase(
            database_path=Path(temporary_directory) / "positions.db",
        )
        await database.connect()

        try:
            await SQLiteMigrationManager(database=database).initialize()
            repository = SQLitePositionRepository(database=database)
            position = _position()
            await repository.save(position=position)

            assert await repository.get_by_symbol(symbol=position.symbol) == position
        finally:
            await database.close()


# =============================================================================
# Phase 5C.4F: entry_client_order_id migration and round-trip tests
# =============================================================================

_ENTRY_CLIENT_ORDER_ID = "btg-639023b2e35c4e56801b2a61746da4dc"


def _position_with_entry_id() -> Position:
    """Build a position that includes a durable entry identity."""
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("4361"),
        entry_price=Decimal("0.02905"),
        current_price=Decimal("0.02905"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        entry_client_order_id=_ENTRY_CLIENT_ORDER_ID,
    )


def test_sqlite_position_entry_client_order_id_round_trips() -> None:
    """entry_client_order_id persists and restores exactly via migration 11."""
    asyncio.run(_run_entry_id_round_trip_test())


def test_sqlite_position_null_entry_client_order_id_loads_successfully() -> None:
    """Old rows without entry_client_order_id (NULL) load without error."""
    asyncio.run(_run_null_entry_id_test())


def test_sqlite_migration_is_idempotent_and_preserves_existing_data() -> None:
    """Running migrations twice does not destroy existing position data."""
    asyncio.run(_run_migration_idempotent_test())


async def _run_entry_id_round_trip_test() -> None:
    with TemporaryDirectory() as tmp:
        db = SQLiteDatabase(database_path=Path(tmp) / "pos.db")
        await db.connect()
        try:
            await SQLiteMigrationManager(database=db).initialize()
            repo = SQLitePositionRepository(database=db)
            position = _position_with_entry_id()
            await repo.save(position=position)
            loaded = await repo.get_by_symbol(symbol=position.symbol)
            assert loaded is not None
            assert loaded.entry_client_order_id == _ENTRY_CLIENT_ORDER_ID
            assert loaded == position
        finally:
            await db.close()


async def _run_null_entry_id_test() -> None:
    """Position without entry_client_order_id loads with None value."""
    with TemporaryDirectory() as tmp:
        db = SQLiteDatabase(database_path=Path(tmp) / "pos.db")
        await db.connect()
        try:
            await SQLiteMigrationManager(database=db).initialize()
            repo = SQLitePositionRepository(database=db)
            position = _position()  # no entry_client_order_id → None
            await repo.save(position=position)
            loaded = await repo.get_by_symbol(symbol=position.symbol)
            assert loaded is not None
            assert loaded.entry_client_order_id is None
        finally:
            await db.close()


async def _run_migration_idempotent_test() -> None:
    """Migrations can be initialized twice; existing data is preserved."""
    with TemporaryDirectory() as tmp:
        db = SQLiteDatabase(database_path=Path(tmp) / "pos.db")
        await db.connect()
        try:
            mgr = SQLiteMigrationManager(database=db)
            v1 = await mgr.initialize()

            # Save a position before the second initialize call
            repo = SQLitePositionRepository(database=db)
            position = _position_with_entry_id()
            await repo.save(position=position)

            # Second initialize call should be a no-op (version unchanged)
            v2 = await mgr.initialize()
            assert v1 == v2

            # Position must still be intact
            loaded = await repo.get_by_symbol(symbol=position.symbol)
            assert loaded is not None
            assert loaded.entry_client_order_id == _ENTRY_CLIENT_ORDER_ID
        finally:
            await db.close()

def test_sqlite_v10_to_v11_migration_preserves_legacy_position() -> None:
    """Upgrade a real v10 row to v11 without losing position metadata."""
    asyncio.run(_run_v10_to_v11_migration_test())


async def _run_v10_to_v11_migration_test() -> None:
    """Migrate one historical positions row from schema v10 to v11."""
    with TemporaryDirectory() as temporary_directory:
        database = SQLiteDatabase(
            database_path=Path(temporary_directory) / "migration-v10-v11.db",
        )
        await database.connect()

        try:
            manager = SQLiteMigrationManager(database=database)

            version_10 = await manager.initialize(target_version=10)
            assert version_10 == 10

            columns_before = await database.fetch_all(
                statement="PRAGMA table_info(positions)",
            )
            assert "entry_client_order_id" not in {
                str(row["name"]) for row in columns_before
            }

            await database.execute(
                statement="""
                INSERT INTO positions (
                    symbol,
                    side,
                    quantity,
                    entry_price,
                    current_price,
                    unrealized_pnl,
                    leverage,
                    opened_at,
                    updated_at,
                    stop_loss,
                    take_profit,
                    interval,
                    strategy_type,
                    protection_step,
                    stop_loss_client_algo_id,
                    take_profit_client_algo_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                parameters=(
                    "1000BONKUSDT",
                    PositionSide.LONG.value,
                    "4361",
                    "0.00229",
                    "0.00229",
                    "0",
                    1,
                    _NOW.isoformat(),
                    _NOW.isoformat(),
                    None,
                    None,
                    Interval.M15.value,
                    StrategyType.EMA_CROSS.value,
                    0,
                    "bsl-5e874580885b4fc1842dc6fb6677469b",
                    "btp-49dbe248896142829376fad033a40165",
                ),
            )

            version_11 = await manager.initialize()
            assert version_11 == manager.latest_version
            assert version_11 == 11

            repository = SQLitePositionRepository(database=database)
            loaded = await repository.get_by_symbol(symbol="1000BONKUSDT")

            assert loaded is not None
            assert loaded.symbol == "1000BONKUSDT"
            assert loaded.side is PositionSide.LONG
            assert loaded.quantity == Decimal("4361")
            assert loaded.interval is Interval.M15
            assert loaded.strategy_type is StrategyType.EMA_CROSS
            assert (
                loaded.stop_loss_client_algo_id
                == "bsl-5e874580885b4fc1842dc6fb6677469b"
            )
            assert (
                loaded.take_profit_client_algo_id
                == "btp-49dbe248896142829376fad033a40165"
            )
            assert loaded.entry_client_order_id is None

            columns_after = await database.fetch_all(
                statement="PRAGMA table_info(positions)",
            )
            assert "entry_client_order_id" in {
                str(row["name"]) for row in columns_after
            }

            version_again = await manager.initialize()
            assert version_again == 11

            loaded_again = await repository.get_by_symbol(
                symbol="1000BONKUSDT",
            )
            assert loaded_again == loaded
        finally:
            await database.close()
