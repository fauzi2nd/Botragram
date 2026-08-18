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
