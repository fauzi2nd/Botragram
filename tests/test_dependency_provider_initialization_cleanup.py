"""Dependency-provider startup resource cleanup regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from botragram.app import DependencyProvider
from botragram.storage.sqlite import SQLiteDatabase, SQLiteMigrationManager


@pytest.mark.asyncio
async def test_initialization_failure_closes_connected_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Close a connected database even before repository ownership is built."""
    events: list[str] = []

    async def connect(database: SQLiteDatabase) -> None:
        events.append(f"connect:{database.database_path}")

    async def fail_migration(manager: SQLiteMigrationManager) -> None:
        del manager
        raise RuntimeError("configured migration failure")

    async def close(database: SQLiteDatabase) -> None:
        events.append(f"close:{database.database_path}")

    monkeypatch.setattr(SQLiteDatabase, "connect", connect)
    monkeypatch.setattr(SQLiteMigrationManager, "initialize", fail_migration)
    monkeypatch.setattr(SQLiteDatabase, "close", close)
    database_path = tmp_path / "botragram.db"
    provider = DependencyProvider(database_path=database_path)

    with pytest.raises(RuntimeError, match="configured migration failure"):
        await provider.initialize()

    assert events == [
        f"connect:{database_path}",
        f"close:{database_path}",
    ]
    assert not provider.is_initialized
