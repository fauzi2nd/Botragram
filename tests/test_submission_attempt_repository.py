"""Durable submission-attempt repository tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from botragram.enums import (
    Interval,
    OrderSide,
    OrderType,
    SubmissionAttemptStatus,
)
from botragram.models import SubmissionAttempt
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteSubmissionAttemptRepository,
)

_NOW = datetime(2026, 8, 17, tzinfo=UTC)


def _attempt() -> SubmissionAttempt:
    """Build one deterministic prepared submission intent."""
    return SubmissionAttempt(
        client_order_id="btg-00000000000000000000000000000000",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        signal_generated_at=_NOW,
        interval=Interval.M15,
        strategy_type=None,
        status=SubmissionAttemptStatus.PREPARED,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_sqlite_submission_attempt_round_trip_and_lifecycle_update() -> None:
    """Persist a prepared attempt and replace it after acknowledgement."""
    asyncio.run(_run_sqlite_submission_attempt_test())


async def _run_sqlite_submission_attempt_test() -> None:
    """Exercise durable retrieval and unresolved filtering."""
    with TemporaryDirectory() as temporary_directory:
        database = SQLiteDatabase(
            database_path=Path(temporary_directory) / "attempts.db",
        )
        await database.connect()

        try:
            await SQLiteMigrationManager(database=database).initialize()
            repository = SQLiteSubmissionAttemptRepository(database=database)
            attempt = _attempt()
            assert await repository.reserve(attempt=attempt)

            assert (
                await repository.get_by_client_order_id(
                    client_order_id=attempt.client_order_id
                )
                == attempt
            )
            assert await repository.get_unresolved() == (attempt,)

            acknowledged = replace(
                attempt,
                status=SubmissionAttemptStatus.ACKNOWLEDGED,
                exchange_order_id="123",
            )
            await repository.save(attempt=acknowledged)

            assert (
                await repository.get_by_client_order_id(
                    client_order_id=attempt.client_order_id
                )
                == acknowledged
            )
            assert await repository.get_unresolved() == ()
            # If an acknowledged attempt is transitioned to the resolved-no-exposure
            # terminal state it must be excluded from incomplete lists.
            resolved = replace(
                acknowledged,
                status=SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE,
            )
            await repository.save(attempt=resolved)
            assert await repository.get_incomplete() == ()
        finally:
            await database.close()


def test_sqlite_reservation_is_atomic_across_database_connections() -> None:
    """Allow only one prepared owner across two repository connections."""
    asyncio.run(_run_cross_connection_reservation_test())


async def _run_cross_connection_reservation_test() -> None:
    """Exercise the reservation statement against one shared SQLite database."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "attempt-reservation.db"
        first_database = SQLiteDatabase(database_path=database_path)
        second_database = SQLiteDatabase(database_path=database_path)
        await first_database.connect()
        await second_database.connect()

        try:
            await SQLiteMigrationManager(database=first_database).initialize()
            first_repository = SQLiteSubmissionAttemptRepository(
                database=first_database
            )
            second_repository = SQLiteSubmissionAttemptRepository(
                database=second_database
            )
            first_attempt = _attempt()
            second_attempt = replace(
                first_attempt,
                client_order_id="btg-11111111111111111111111111111111",
            )

            reserved = await asyncio.gather(
                first_repository.reserve(attempt=first_attempt),
                second_repository.reserve(attempt=second_attempt),
            )

            assert reserved.count(True) == 1
            assert reserved.count(False) == 1
            incomplete = await first_repository.get_incomplete()
            assert len(incomplete) == 1
            assert incomplete[0].client_order_id in {
                first_attempt.client_order_id,
                second_attempt.client_order_id,
            }
        finally:
            await second_database.close()
            await first_database.close()
