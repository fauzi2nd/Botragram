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
async def test_sqlite_runtime_settings_repository(tmp_path: Path) -> None:
    """Verify SQLite repository stores, updates, and returns runtime settings."""
    db_path = tmp_path / "runtime_settings_test.db"
    database = SQLiteDatabase(database_path=db_path)
    await database.connect()

    migration_manager = SQLiteMigrationManager(database=database)
    version = await migration_manager.initialize()
    assert version >= 19

    repo = SQLiteRuntimeSettingsRepository(database=database)

    # Initially empty
    assert await repo.get_strategy() is None
    assert await repo.get_leverage() is None
    assert await repo.get_dynamic_leverage() is None

    # Save initial strategy, leverage, and dynamic leverage
    await repo.save_strategy(strategy_type=StrategyType.EMA_SCALPING)
    await repo.save_leverage(leverage=5)
    await repo.save_dynamic_leverage(enabled=True)
    assert await repo.get_strategy() is StrategyType.EMA_SCALPING
    assert await repo.get_leverage() == 5
    assert await repo.get_dynamic_leverage() is True

    # Update strategy, leverage, and dynamic leverage
    await repo.save_strategy(strategy_type=StrategyType.ADX_TREND)
    await repo.save_leverage(leverage=10)
    await repo.save_dynamic_leverage(enabled=False)
    assert await repo.get_strategy() is StrategyType.ADX_TREND
    assert await repo.get_leverage() == 10
    assert await repo.get_dynamic_leverage() is False

    # Reject non-positive leverage
    with pytest.raises(ValueError, match="positive integer"):
        await repo.save_leverage(leverage=0)

    await database.close()


@pytest.mark.asyncio
async def test_memory_runtime_settings_repository() -> None:
    """Verify Memory repository stores and returns configured settings."""
    repo = MemoryRuntimeSettingsRepository()
    assert await repo.get_strategy() is None
    assert await repo.get_leverage() is None
    assert await repo.get_dynamic_leverage() is None

    await repo.save_strategy(strategy_type=StrategyType.SUPERTREND)
    await repo.save_leverage(leverage=20)
    await repo.save_dynamic_leverage(enabled=True)
    assert await repo.get_strategy() is StrategyType.SUPERTREND
    assert await repo.get_leverage() == 20
    assert await repo.get_dynamic_leverage() is True

    init_repo = MemoryRuntimeSettingsRepository(
        strategy_type=StrategyType.EMA_CROSS,
        leverage=15,
        dynamic_leverage=False,
    )
    assert await init_repo.get_strategy() is StrategyType.EMA_CROSS
    assert await init_repo.get_leverage() == 15
    assert await init_repo.get_dynamic_leverage() is False
