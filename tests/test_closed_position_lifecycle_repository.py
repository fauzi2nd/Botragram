"""SQLite closed-position lifecycle durability and migration regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    OrderSide,
    PositionSide,
)
from botragram.models import (
    ClosedPositionLifecycle,
    PendingClosedPositionLifecycle,
    Trade,
)
from botragram.storage.sqlite import (
    SQLiteClosedPositionLifecycleRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteTradeRepository,
)

_NOW = datetime(2026, 8, 26, tzinfo=UTC)
_ENTRY_ID = "btg-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _pending() -> PendingClosedPositionLifecycle:
    """Build exact lifecycle ownership."""
    return PendingClosedPositionLifecycle(
        entry_client_order_id=_ENTRY_ID,
        symbol="BTCUSDT",
        position_side=PositionSide.LONG,
        entry_order_id="entry-1",
        exit_client_order_id="btp-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        exit_order_id="exit-1",
        close_reason=ClosedPositionReason.TAKE_PROFIT,
        provenance=ClosedPositionProvenance.PROTECTION_ORDER,
        recorded_at=_NOW,
    )


def _completed() -> ClosedPositionLifecycle:
    """Build exact immutable financial completion."""
    return ClosedPositionLifecycle(
        ownership=_pending(),
        gross_realized_pnl=Decimal("2"),
        fee=Decimal("0.5"),
        fee_asset="USDT",
        net_pnl=Decimal("1.5"),
        closed_at=_NOW,
    )


@pytest.mark.asyncio
async def test_v15_does_not_backfill_unverifiable_historical_fills() -> None:
    """Leave legacy fills out when Botragram lifecycle ownership is absent."""
    with TemporaryDirectory() as temporary_directory:
        database = SQLiteDatabase(
            database_path=Path(temporary_directory) / "no-backfill.db"
        )
        await database.connect()
        try:
            manager = SQLiteMigrationManager(database=database)
            assert await manager.initialize(target_version=14) == 14
            await SQLiteTradeRepository(database=database).save(
                trade=Trade(
                    trade_id="legacy-fill",
                    order_id="legacy-exit",
                    symbol="BTCUSDT",
                    side=OrderSide.SELL,
                    price=Decimal("101"),
                    quantity=Decimal("1"),
                    quote_quantity=Decimal("101"),
                    fee=Decimal("0.1"),
                    fee_asset="USDT",
                    realized_pnl=Decimal("1"),
                    executed_at=_NOW,
                )
            )

            assert await manager.initialize(target_version=15) == 15
            repository = SQLiteClosedPositionLifecycleRepository(database=database)

            assert await repository.get_pending() == ()
            assert await repository.get_completed() == ()
        finally:
            await database.close()


@pytest.mark.asyncio
async def test_lifecycle_identity_is_durable_and_idempotent_after_reopen() -> None:
    """Persist exactly one completed trade across process-like restart replay."""
    with TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "lifecycle.db"
        first_database = SQLiteDatabase(database_path=path)
        await first_database.connect()
        try:
            manager = SQLiteMigrationManager(database=first_database)
            assert await manager.initialize() == manager.latest_version
            first_repository = SQLiteClosedPositionLifecycleRepository(
                database=first_database
            )
            await first_repository.stage(lifecycle=_pending())
            await first_repository.stage(lifecycle=_pending())
            await first_repository.complete(lifecycle=_completed())
            await first_repository.complete(lifecycle=_completed())
        finally:
            await first_database.close()

        second_database = SQLiteDatabase(database_path=path)
        await second_database.connect()
        try:
            second_repository = SQLiteClosedPositionLifecycleRepository(
                database=second_database
            )
            await second_repository.stage(lifecycle=_pending())
            await second_repository.complete(lifecycle=_completed())

            assert await second_repository.get_pending() == ()
            assert await second_repository.get_completed() == (_completed(),)
        finally:
            await second_database.close()
