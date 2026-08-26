"""Regression tests for one-time TESTNET legacy LIVE ledger migration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteTestnetLegacyLiveLedgerMigration,
)

_TIMESTAMP = "2026-08-25T00:00:00+00:00"
_SOURCE_POSITION_SQL = """
INSERT INTO positions (
    symbol, side, quantity, entry_price, current_price, unrealized_pnl,
    leverage, opened_at, updated_at, stop_loss, take_profit, interval,
    strategy_type, protection_step, stop_loss_client_algo_id,
    take_profit_client_algo_id, entry_client_order_id, pending_stop_loss,
    pending_stop_loss_client_algo_id, pending_protection_step
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""
_SOURCE_ORDER_SQL = """
INSERT INTO orders (
    symbol, order_id, side, order_type, status, quantity, executed_quantity,
    created_at, updated_at, price, stop_price, client_order_id
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""
_SOURCE_TRADE_SQL = """
INSERT INTO trades (
    symbol, trade_id, order_id, side, price, quantity, quote_quantity, fee,
    fee_asset, realized_pnl, executed_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""
_SOURCE_ATTEMPT_SQL = """
INSERT INTO submission_attempts (
    client_order_id, symbol, side, order_type, quantity, signal_generated_at,
    interval, strategy_type, status, exchange_order_id, created_at, updated_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""
_SOURCE_CLAIM_SQL = """
INSERT INTO autonomous_live_opportunity_claims (
    symbol, interval, strategy_name, signal_generated_at
)
VALUES (?, ?, ?, ?);
"""


def test_migrates_legacy_testnet_ledger_into_target_without_durable_records() -> None:
    """Restore durable Botragram identity and outcome ledger exactly once."""
    asyncio.run(_run_legacy_ledger_migration_test())


async def _run_legacy_ledger_migration_test() -> None:
    """Import a complete compatible legacy ledger into an empty target."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = SQLiteDatabase(database_path=root / "botragram.db")
        target = SQLiteDatabase(
            database_path=root / "botragram-binance-futures-testnet.db"
        )
        await source.connect()
        await target.connect()
        try:
            await SQLiteMigrationManager(database=source).initialize()
            await SQLiteMigrationManager(database=target).initialize()
            await _seed_source(database=source)
            await _seed_undurable_target_position(database=target)

            migration = SQLiteTestnetLegacyLiveLedgerMigration(
                target_database=target,
                source_database_path=source.database_path,
            )

            assert await migration.migrate_if_required() is True
            assert await migration.migrate_if_required() is False
            assert await _count(database=target, table_name="orders") == 1
            assert await _count(database=target, table_name="trades") == 1
            assert await _count(database=target, table_name="submission_attempts") == 1
            assert (
                await _count(
                    database=target,
                    table_name="autonomous_live_opportunity_claims",
                )
                == 1
            )
            position = await target.fetch_one(
                statement="""
                SELECT entry_client_order_id
                FROM positions
                WHERE symbol = ?;
                """,
                parameters=("EULUSDT",),
            )
            assert position is not None
            assert position[0] == "btg-entry"
            source_trade_count = await _count(database=source, table_name="trades")
            assert source_trade_count == 1
        finally:
            await target.close()
            await source.close()


def test_skips_older_legacy_schema_for_existing_durable_target() -> None:
    """Do not inspect an obsolete source after target ownership is established."""
    asyncio.run(_run_existing_target_ledger_test())


async def _run_existing_target_ledger_test() -> None:
    """Leave target state untouched even when the legacy schema is older."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = SQLiteDatabase(database_path=root / "botragram.db")
        target = SQLiteDatabase(
            database_path=root / "botragram-binance-futures-testnet.db"
        )
        await source.connect()
        await target.connect()
        try:
            await SQLiteMigrationManager(database=source).initialize()
            await SQLiteMigrationManager(database=target).initialize()
            await _seed_source(database=source)
            await target.execute(
                statement=_SOURCE_ATTEMPT_SQL,
                parameters=(
                    "target-entry",
                    "BTCUSDT",
                    "buy",
                    "market",
                    "1",
                    _TIMESTAMP,
                    "1m",
                    "ema_cross",
                    "completed",
                    "target-order",
                    _TIMESTAMP,
                    _TIMESTAMP,
                ),
            )
            await source.execute(
                statement="UPDATE schema_version SET version = ?;",
                parameters=(14,),
            )

            migration = SQLiteTestnetLegacyLiveLedgerMigration(
                target_database=target,
                source_database_path=source.database_path,
            )

            assert await migration.migrate_if_required() is False
            assert await _count(database=target, table_name="trades") == 0
            assert await _count(database=target, table_name="submission_attempts") == 1
        finally:
            await target.close()
            await source.close()


def test_rejects_older_legacy_schema_when_target_requires_import() -> None:
    """Require exact schema compatibility before importing into an empty target."""
    asyncio.run(_run_incompatible_legacy_schema_test())


async def _run_incompatible_legacy_schema_test() -> None:
    """Reject an older source only when its rows would otherwise be imported."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = SQLiteDatabase(database_path=root / "botragram.db")
        target = SQLiteDatabase(
            database_path=root / "botragram-binance-futures-testnet.db"
        )
        await source.connect()
        await target.connect()
        try:
            await SQLiteMigrationManager(database=source).initialize()
            await SQLiteMigrationManager(database=target).initialize()
            await _seed_source(database=source)
            await source.execute(
                statement="UPDATE schema_version SET version = ?;",
                parameters=(14,),
            )
            migration = SQLiteTestnetLegacyLiveLedgerMigration(
                target_database=target,
                source_database_path=source.database_path,
            )

            with pytest.raises(RuntimeError, match="source=14 target=15"):
                await migration.migrate_if_required()
        finally:
            await target.close()
            await source.close()


async def _seed_source(*, database: SQLiteDatabase) -> None:
    """Persist one complete durable Botragram LIVE ledger sample."""
    await database.execute(
        statement=_SOURCE_POSITION_SQL,
        parameters=(
            "EULUSDT",
            "short",
            "1",
            "1.40",
            "1.38",
            "0.02",
            1,
            _TIMESTAMP,
            _TIMESTAMP,
            "1.45",
            "1.35",
            "1m",
            "ema_cross",
            0,
            "bsl-stop",
            "btp-take",
            "btg-entry",
            None,
            None,
            0,
        ),
    )
    await database.execute(
        statement=_SOURCE_ORDER_SQL,
        parameters=(
            "EULUSDT",
            "entry-order",
            "sell",
            "market",
            "filled",
            "1",
            "1",
            _TIMESTAMP,
            _TIMESTAMP,
            None,
            None,
            "btg-entry",
        ),
    )
    await database.execute(
        statement=_SOURCE_TRADE_SQL,
        parameters=(
            "EULUSDT",
            "exit-trade",
            "exit-order",
            "buy",
            "1.35",
            "1",
            "1.35",
            "0.01",
            "USDT",
            "0.05",
            _TIMESTAMP,
        ),
    )
    await database.execute(
        statement=_SOURCE_ATTEMPT_SQL,
        parameters=(
            "btg-entry",
            "EULUSDT",
            "sell",
            "market",
            "1",
            _TIMESTAMP,
            "1m",
            "ema_cross",
            "completed",
            "entry-order",
            _TIMESTAMP,
            _TIMESTAMP,
        ),
    )
    await database.execute(
        statement=_SOURCE_CLAIM_SQL,
        parameters=("EULUSDT", "1m", "ema_cross", _TIMESTAMP),
    )


async def _seed_undurable_target_position(*, database: SQLiteDatabase) -> None:
    """Persist the non-authoritative snapshot shape caused by the old split."""
    await database.execute(
        statement=_SOURCE_POSITION_SQL,
        parameters=(
            "EULUSDT",
            "short",
            "1",
            "1.40",
            "1.38",
            "0.02",
            1,
            _TIMESTAMP,
            _TIMESTAMP,
            "1.45",
            "1.35",
            "1m",
            "ema_cross",
            0,
            None,
            None,
            None,
            None,
            None,
            0,
        ),
    )


async def _count(*, database: SQLiteDatabase, table_name: str) -> int:
    """Return one test table's record count."""
    row = await database.fetch_one(statement=f"SELECT COUNT(*) FROM {table_name};")
    assert row is not None
    count: object = row[0]
    assert isinstance(count, int)
    return count
