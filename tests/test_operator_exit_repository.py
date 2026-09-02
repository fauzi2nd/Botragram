"""SQLite operator-exit migration and persistence regression tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from botragram.enums import (
    ExecutionPolicy,
    OperatorExitStatus,
    OperatorExitType,
)
from botragram.models import OperatorExitOperation
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteOperatorExitRepository,
)

_NOW = datetime(2026, 8, 28, tzinfo=UTC)


@pytest.mark.asyncio
async def test_migration_17_adds_operator_exit_tables(tmp_path: Path) -> None:
    database = SQLiteDatabase(database_path=tmp_path / "botragram.db")
    await database.connect()
    try:
        manager = SQLiteMigrationManager(database=database)
        assert await manager.initialize(target_version=16) == 16
        before = await database.fetch_all(
            statement=(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name LIKE 'operator_exit_%' "
                "ORDER BY name;"
            )
        )
        assert before == ()

        assert await manager.initialize(target_version=17) == 17
        after = await database.fetch_all(
            statement=(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name LIKE 'operator_exit_%' "
                "ORDER BY name;"
            )
        )
        assert tuple(str(row["name"]) for row in after) == (
            "operator_exit_attempts",
            "operator_exit_operations",
        )

        assert await manager.initialize(target_version=18) == 18
        columns = await database.fetch_all(
            statement="PRAGMA table_info(operator_exit_operations);"
        )
        assert "authorized_symbols" in {str(row["name"]) for row in columns}
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_sqlite_switch_pending_remains_incomplete(tmp_path: Path) -> None:
    database = SQLiteDatabase(database_path=tmp_path / "botragram.db")
    await database.connect()
    try:
        await SQLiteMigrationManager(database=database).initialize()
        repository = SQLiteOperatorExitRepository(database=database)
        operation = OperatorExitOperation(
            operation_id="operation-1",
            operation_type=OperatorExitType.FLATTEN_AND_SWITCH,
            status=OperatorExitStatus.SWITCH_PENDING,
            requested_by="telegram:7",
            authorized_symbols=("BTCUSDT", "ETHUSDT"),
            target_execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER,
            created_at=_NOW,
            updated_at=_NOW,
        )

        assert await repository.reserve_operation(operation=operation)
        incomplete = tuple(await repository.get_incomplete_operations())

        assert incomplete == (operation,)
    finally:
        await database.close()
