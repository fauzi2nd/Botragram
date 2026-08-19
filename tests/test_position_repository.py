"""Durable position protection-identity repository tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from botragram.enums import PositionSide
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
