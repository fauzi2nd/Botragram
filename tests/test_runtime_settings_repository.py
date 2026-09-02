"""
Botragram

Description:
    Tests for SQLite and in-memory RuntimeSettingsRepository.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from pathlib import Path

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import StrategyType
from botragram.storage.memory import MemoryRuntimeSettingsRepository
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteRuntimeSettingsRepository,
)


# =============================================================================
# Tests
# =============================================================================
@pytest.mark.asyncio
async def test_sqlite_runtime_settings_repository_lifecycle(tmp_path: Path) -> None:
    """Verify SQLite repository persists, retrieves, and updates runtime strategy."""
    db_path = tmp_path / "test_settings.db"
    database = SQLiteDatabase(database_path=db_path)
    await database.connect()

    migration_manager = SQLiteMigrationManager(database=database)
    version = await migration_manager.initialize()
    assert version >= 19

    repo = SQLiteRuntimeSettingsRepository(database=database)

    # Initially empty
    assert await repo.get_strategy() is None

    # Save initial strategy
    await repo.save_strategy(strategy_type=StrategyType.EMA_SCALPING)
    assert await repo.get_strategy() is StrategyType.EMA_SCALPING

    # Update strategy
    await repo.save_strategy(strategy_type=StrategyType.ADX_TREND)
    assert await repo.get_strategy() is StrategyType.ADX_TREND

    await database.close()


@pytest.mark.asyncio
async def test_memory_runtime_settings_repository() -> None:
    """Verify Memory repository stores and returns configured strategy."""
    repo = MemoryRuntimeSettingsRepository()
    assert await repo.get_strategy() is None

    await repo.save_strategy(strategy_type=StrategyType.SUPERTREND)
    assert await repo.get_strategy() is StrategyType.SUPERTREND

    init_repo = MemoryRuntimeSettingsRepository(
        strategy_type=StrategyType.EMA_CROSS,
    )
    assert await init_repo.get_strategy() is StrategyType.EMA_CROSS
