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

from decimal import Decimal

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
    """Verify SQLite repository persists, retrieves, and updates runtime settings."""
    db_path = tmp_path / "test_settings.db"
    database = SQLiteDatabase(database_path=db_path)
    await database.connect()

    migration_manager = SQLiteMigrationManager(database=database)
    version = await migration_manager.initialize()
    assert version >= 19

    repo = SQLiteRuntimeSettingsRepository(database=database)

    # Initially empty
    assert await repo.get_strategy() is None
    assert await repo.get_leverage() is None
    assert await repo.get_trailing_stop() is None

    # Save initial strategy, leverage, and trailing stop
    await repo.save_strategy(strategy_type=StrategyType.EMA_SCALPING)
    await repo.save_leverage(leverage=5)
    await repo.save_trailing_stop(
        enabled=True,
        trigger_pct=Decimal("0.02"),
        distance_pct=Decimal("0.01"),
    )
    assert await repo.get_strategy() is StrategyType.EMA_SCALPING
    assert await repo.get_leverage() == 5
    trailing = await repo.get_trailing_stop()
    assert trailing == (True, Decimal("0.02"), Decimal("0.01"))

    # Update strategy, leverage, and trailing stop
    await repo.save_strategy(strategy_type=StrategyType.ADX_TREND)
    await repo.save_leverage(leverage=10)
    await repo.save_trailing_stop(
        enabled=False,
        trigger_pct=Decimal("0.015"),
        distance_pct=Decimal("0.008"),
    )
    assert await repo.get_strategy() is StrategyType.ADX_TREND
    assert await repo.get_leverage() == 10
    trailing2 = await repo.get_trailing_stop()
    assert trailing2 == (False, Decimal("0.015"), Decimal("0.008"))

    # Reject non-positive leverage
    with pytest.raises(ValueError, match="positive integer"):
        await repo.save_leverage(leverage=0)

    # Reject invalid trailing stop parameters
    with pytest.raises(ValueError, match="strictly less than"):
        await repo.save_trailing_stop(
            enabled=True,
            trigger_pct=Decimal("0.01"),
            distance_pct=Decimal("0.02"),
        )

    await database.close()


@pytest.mark.asyncio
async def test_memory_runtime_settings_repository() -> None:
    """Verify Memory repository stores and returns configured settings."""
    repo = MemoryRuntimeSettingsRepository()
    assert await repo.get_strategy() is None
    assert await repo.get_leverage() is None
    assert await repo.get_trailing_stop() is None

    await repo.save_strategy(strategy_type=StrategyType.SUPERTREND)
    await repo.save_leverage(leverage=20)
    await repo.save_trailing_stop(
        enabled=True,
        trigger_pct=Decimal("0.015"),
        distance_pct=Decimal("0.005"),
    )
    assert await repo.get_strategy() is StrategyType.SUPERTREND
    assert await repo.get_leverage() == 20
    assert await repo.get_trailing_stop() == (
        True,
        Decimal("0.015"),
        Decimal("0.005"),
    )

    init_repo = MemoryRuntimeSettingsRepository(
        strategy_type=StrategyType.EMA_CROSS,
        leverage=15,
        trailing_stop=(False, Decimal("0.02"), Decimal("0.01")),
    )
    assert await init_repo.get_strategy() is StrategyType.EMA_CROSS
    assert await init_repo.get_leverage() == 15
    assert await init_repo.get_trailing_stop() == (
        False,
        Decimal("0.02"),
        Decimal("0.01"),
    )
