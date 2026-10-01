"""Persisted strategy compatibility and PIER-only runtime regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from botragram.app import DependencyProvider
from botragram.config import Settings
from botragram.enums import StrategyType
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteRuntimeSettingsRepository,
)

pytestmark = pytest.mark.usefixtures("stub_binance_time_sync")


@pytest.mark.asyncio
async def test_dependency_provider_ignores_persisted_legacy_strategy(
    tmp_path: Path,
) -> None:
    """Keep old metadata readable without reactivating its removed strategy."""
    database_path = tmp_path / "botragram.db"
    database = SQLiteDatabase(database_path=database_path)
    await database.connect()
    await SQLiteMigrationManager(database=database).initialize()
    repository = SQLiteRuntimeSettingsRepository(database=database)
    await repository.save_strategy(strategy_type=StrategyType.EMA_SCALPING)
    await database.close()

    provider = DependencyProvider(database_path=database_path, settings=Settings())
    async with provider:
        assert (
            provider.runtime_control.configured_strategy_type
            is StrategyType.PINBAR_ENGULFING_EMA_RSI
        )
        assert (
            provider.settings.strategy.strategy_type
            is StrategyType.PINBAR_ENGULFING_EMA_RSI
        )
        assert (
            provider.runtime_control.interval
            is provider.settings.effective_strategy_interval
        )

    database = SQLiteDatabase(database_path=database_path)
    await database.connect()
    repository = SQLiteRuntimeSettingsRepository(database=database)
    assert await repository.get_strategy() is StrategyType.EMA_SCALPING
    await database.close()


@pytest.mark.asyncio
async def test_dependency_provider_restores_persisted_risk_controls(
    tmp_path: Path,
) -> None:
    """Keep unrelated persisted risk controls through PIER-only startup."""
    database_path = tmp_path / "botragram.db"
    database = SQLiteDatabase(database_path=database_path)
    await database.connect()
    await SQLiteMigrationManager(database=database).initialize()
    repository = SQLiteRuntimeSettingsRepository(database=database)
    await repository.save_leverage(leverage=7)
    await repository.save_dynamic_leverage(enabled=True)
    await database.close()

    provider = DependencyProvider(database_path=database_path, settings=Settings())
    async with provider:
        assert provider.settings.risk.leverage == 7
        assert provider.runtime_control.leverage == 7
        assert provider.settings.risk.dynamic_leverage_enabled
        assert provider.runtime_control.dynamic_leverage_enabled


@pytest.mark.asyncio
async def test_runtime_rejects_legacy_strategy_without_persisting_it(
    tmp_path: Path,
) -> None:
    """Reject removed strategies at the provider's concrete strategy boundary."""
    database_path = tmp_path / "botragram.db"
    provider = DependencyProvider(database_path=database_path, settings=Settings())
    async with provider:
        with pytest.raises(ValueError, match="Unsupported strategy type"):
            provider.runtime_control.select_strategy(StrategyType.ADX_TREND)
        assert (
            provider.runtime_control.configured_strategy_type
            is StrategyType.PINBAR_ENGULFING_EMA_RSI
        )
        assert await provider.runtime_settings_repository.get_strategy() is None
