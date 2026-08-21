"""Durable autonomous LIVE closed-candle claim repository tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Signal
from botragram.storage.sqlite import (
    SQLiteAutonomousLiveOpportunityClaimRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
)

_NOW = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)


def _signal(
    *,
    signal_type: SignalType = SignalType.BUY,
    generated_at: datetime = _NOW,
) -> Signal:
    return Signal(
        symbol="btcusdt",
        signal_type=signal_type,
        price=Decimal("100"),
        confidence=Decimal("0.9"),
        strategy_name=StrategyType.EMA_CROSS.value,
        generated_at=generated_at,
    )


def test_sqlite_v11_to_v12_migration_creates_claim_ledger() -> None:
    """Upgrade an existing v11 database before using the new claim ledger."""
    asyncio.run(_run_v11_to_v12_migration_test())


async def _run_v11_to_v12_migration_test() -> None:
    with TemporaryDirectory() as temporary_directory:
        database = SQLiteDatabase(
            database_path=Path(temporary_directory) / "claims-v11-v12.db"
        )
        await database.connect()
        try:
            manager = SQLiteMigrationManager(database=database)
            assert await manager.initialize(target_version=11) == 11

            before = await database.fetch_one(
                statement="""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'autonomous_live_opportunity_claims'
                """
            )
            assert before is None

            assert await manager.initialize() == 12

            after = await database.fetch_one(
                statement="""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'autonomous_live_opportunity_claims'
                """
            )
            assert after is not None

            repository = SQLiteAutonomousLiveOpportunityClaimRepository(
                database=database
            )
            signal = _signal()
            assert await repository.claim(signal=signal, interval=Interval.M15)
            assert not await repository.claim(signal=signal, interval=Interval.M15)
        finally:
            await database.close()


def test_sqlite_claim_is_atomic_and_idempotent() -> None:
    """Only the first exact closed-candle identity may be claimed."""
    asyncio.run(_run_atomic_claim_test())


async def _run_atomic_claim_test() -> None:
    with TemporaryDirectory() as temporary_directory:
        database = SQLiteDatabase(database_path=Path(temporary_directory) / "claims.db")
        await database.connect()
        try:
            manager = SQLiteMigrationManager(database=database)
            assert await manager.initialize() == 12
            repository = SQLiteAutonomousLiveOpportunityClaimRepository(
                database=database
            )
            signal = _signal()

            assert await repository.claim(signal=signal, interval=Interval.M15)
            assert not await repository.claim(signal=signal, interval=Interval.M15)
        finally:
            await database.close()


def test_sqlite_claim_survives_database_reopen() -> None:
    """A durable claim must deny the same opportunity after process-like reopen."""
    asyncio.run(_run_database_reopen_test())


async def _run_database_reopen_test() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "claims-reopen.db"
        signal = _signal()

        first_database = SQLiteDatabase(database_path=database_path)
        await first_database.connect()
        try:
            await SQLiteMigrationManager(database=first_database).initialize()
            first_repository = SQLiteAutonomousLiveOpportunityClaimRepository(
                database=first_database
            )
            assert await first_repository.claim(
                signal=signal,
                interval=Interval.M15,
            )
        finally:
            await first_database.close()

        second_database = SQLiteDatabase(database_path=database_path)
        await second_database.connect()
        try:
            await SQLiteMigrationManager(database=second_database).initialize()
            second_repository = SQLiteAutonomousLiveOpportunityClaimRepository(
                database=second_database
            )
            assert not await second_repository.claim(
                signal=signal,
                interval=Interval.M15,
            )
        finally:
            await second_database.close()


def test_interval_is_part_of_closed_candle_identity() -> None:
    """The same timestamp may be a distinct opportunity on another interval."""
    asyncio.run(_run_interval_identity_test())


async def _run_interval_identity_test() -> None:
    with TemporaryDirectory() as temporary_directory:
        database = SQLiteDatabase(database_path=Path(temporary_directory) / "claims.db")
        await database.connect()
        try:
            await SQLiteMigrationManager(database=database).initialize()
            repository = SQLiteAutonomousLiveOpportunityClaimRepository(
                database=database
            )
            signal = _signal()

            assert await repository.claim(signal=signal, interval=Interval.M15)
            assert await repository.claim(signal=signal, interval=Interval.H1)
        finally:
            await database.close()


def test_direction_is_not_part_of_closed_candle_identity() -> None:
    """Changed signal direction cannot make one closed candle fresh again."""
    asyncio.run(_run_direction_identity_test())


async def _run_direction_identity_test() -> None:
    with TemporaryDirectory() as temporary_directory:
        database = SQLiteDatabase(database_path=Path(temporary_directory) / "claims.db")
        await database.connect()
        try:
            await SQLiteMigrationManager(database=database).initialize()
            repository = SQLiteAutonomousLiveOpportunityClaimRepository(
                database=database
            )
            buy = _signal(signal_type=SignalType.BUY)
            sell = replace(buy, signal_type=SignalType.SELL)

            assert await repository.claim(signal=buy, interval=Interval.M15)
            assert not await repository.claim(signal=sell, interval=Interval.M15)
        finally:
            await database.close()


def test_claim_rejects_non_actionable_and_naive_signal_time() -> None:
    """Replay ledger accepts only actionable timezone-aware signal identities."""
    asyncio.run(_run_claim_validation_test())


async def _run_claim_validation_test() -> None:
    with TemporaryDirectory() as temporary_directory:
        database = SQLiteDatabase(database_path=Path(temporary_directory) / "claims.db")
        await database.connect()
        try:
            await SQLiteMigrationManager(database=database).initialize()
            repository = SQLiteAutonomousLiveOpportunityClaimRepository(
                database=database
            )

            with pytest.raises(ValueError, match="BUY or SELL"):
                await repository.claim(
                    signal=_signal(signal_type=SignalType.HOLD),
                    interval=Interval.M15,
                )

            with pytest.raises(ValueError, match="timezone-aware"):
                await repository.claim(
                    signal=_signal(generated_at=datetime(2026, 8, 21, 15, 0)),
                    interval=Interval.M15,
                )
        finally:
            await database.close()
