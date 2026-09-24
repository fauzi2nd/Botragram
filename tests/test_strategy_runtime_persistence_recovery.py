"""
Botragram

Description:
    Tests for strategy runtime persistence and crash recovery.

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
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import DependencyProvider
from botragram.config import Settings
from botragram.enums import Interval, StrategyType
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteRuntimeSettingsRepository,
)

_TMP_DIRS: list[object] = []


def _get_temp_db_path() -> Path:
    tmp = TemporaryDirectory()
    _TMP_DIRS.append(tmp)
    return Path(tmp.name) / "test_persistence.db"


@pytest.mark.asyncio
async def test_dependency_provider_loads_persisted_strategy_on_boot() -> None:
    """Verify DependencyProvider prioritizes database strategy over default."""
    db_path = _get_temp_db_path()

    # Pre-populate database with a previously chosen strategy
    database = SQLiteDatabase(database_path=db_path)
    await database.connect()
    await SQLiteMigrationManager(database=database).initialize()
    repo = SQLiteRuntimeSettingsRepository(database=database)
    await repo.save_strategy(strategy_type=StrategyType.EMA_SCALPING)
    await database.close()

    # Boot DependencyProvider with default settings (which default to EMA_CROSS)
    provider = DependencyProvider(database_path=db_path, settings=Settings())
    await provider.initialize()

    try:
        # Runtime control and settings should have adopted EMA_SCALPING
        assert provider.runtime_control.strategy_type is StrategyType.EMA_SCALPING
        assert provider.runtime_control.interval is Interval.M5
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_runtime_strategy_selection_persists_to_database() -> None:
    """Verify changing strategy via runtime control persists and survives restart."""
    db_path = _get_temp_db_path()

    provider1 = DependencyProvider(database_path=db_path, settings=Settings())
    await provider1.initialize()

    try:
        # Change strategy at runtime while paused
        provider1.runtime_control.select_strategy(StrategyType.ADX_TREND)
        # Give event loop a tick to process background persistence task
        await asyncio.sleep(0.05)
    finally:
        await provider1.close()

    # Verify directly from database
    database = SQLiteDatabase(database_path=db_path)
    await database.connect()
    repo = SQLiteRuntimeSettingsRepository(database=database)
    persisted = await repo.get_strategy()
    await database.close()

    assert persisted is StrategyType.ADX_TREND

    # Boot a second provider to simulate restart after crash
    provider2 = DependencyProvider(database_path=db_path, settings=Settings())
    await provider2.initialize()

    try:
        assert provider2.runtime_control.strategy_type is StrategyType.ADX_TREND
        assert provider2.runtime_control.interval is Interval.M5
    finally:
        await provider2.close()


@pytest.mark.asyncio
async def test_persisted_strategy_updates_strategy_interval_on_boot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify persisted strategy re-resolves strategy-specific interval."""
    test_env = tmp_path / "test.env"
    test_env.write_text("")
    monkeypatch.setenv("BOTRAGRAM_ENV_FILE", str(test_env))
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)
    monkeypatch.setenv("TRADE_MODE", "PAPER")
    monkeypatch.setenv("EXECUTION_POLICY", "single_symbol")
    monkeypatch.setenv("AUTONOMOUS_LIVE_ENTRY_ENABLED", "false")
    monkeypatch.setenv("AUTONOMOUS_MAINNET_ENTRY_ENABLED", "false")
    monkeypatch.setenv("STRATEGY_TYPE", "botragram_origin")
    monkeypatch.setenv("ORIGIN_INTERVAL", "3m")
    monkeypatch.setenv("PIER_INTERVAL", "15m")
    from botragram.app.environment_provider import EnvironmentProvider
    from botragram.app.settings_manager import SettingsManager

    env_provider = EnvironmentProvider(env_path=str(test_env))
    settings = SettingsManager(environment_provider=env_provider).load()
    assert settings.strategy.strategy_interval is Interval.M3
    assert settings.strategy.strategy_interval_source == "ORIGIN_INTERVAL"

    db_path = _get_temp_db_path()
    database = SQLiteDatabase(database_path=db_path)
    await database.connect()
    await SQLiteMigrationManager(database=database).initialize()
    repo = SQLiteRuntimeSettingsRepository(database=database)
    await repo.save_strategy(strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI)
    await database.close()

    provider = DependencyProvider(database_path=db_path, settings=settings)
    await provider.initialize()

    try:
        assert (
            provider.runtime_control.strategy_type
            is StrategyType.PINBAR_ENGULFING_EMA_RSI
        )
        assert provider.runtime_control.interval is Interval.M15
        assert provider.settings.strategy.strategy_interval is Interval.M15
        assert provider.settings.strategy.strategy_interval_source == "PIER_INTERVAL"
        assert provider.settings.effective_strategy_interval is Interval.M15
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_runtime_strategy_selection_updates_interval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify selecting strategy via runtime control updates strategy interval."""
    test_env = tmp_path / "test.env"
    test_env.write_text("")
    monkeypatch.setenv("BOTRAGRAM_ENV_FILE", str(test_env))
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)
    monkeypatch.setenv("TRADE_MODE", "PAPER")
    monkeypatch.setenv("EXECUTION_POLICY", "single_symbol")
    monkeypatch.setenv("AUTONOMOUS_LIVE_ENTRY_ENABLED", "false")
    monkeypatch.setenv("AUTONOMOUS_MAINNET_ENTRY_ENABLED", "false")
    monkeypatch.setenv("STRATEGY_TYPE", "botragram_origin")
    monkeypatch.setenv("ORIGIN_INTERVAL", "3m")
    monkeypatch.setenv("PIER_INTERVAL", "15m")
    from botragram.app.environment_provider import EnvironmentProvider
    from botragram.app.settings_manager import SettingsManager

    env_provider = EnvironmentProvider(env_path=str(test_env))
    settings = SettingsManager(environment_provider=env_provider).load()
    db_path = _get_temp_db_path()

    provider = DependencyProvider(database_path=db_path, settings=settings)
    await provider.initialize()

    try:
        assert provider.runtime_control.strategy_type is StrategyType.BOTRAGRAM_ORIGIN
        assert provider.runtime_control.interval is Interval.M3

        provider.runtime_control.select_strategy(StrategyType.PINBAR_ENGULFING_EMA_RSI)
        await asyncio.sleep(0.05)

        assert (
            getattr(provider.runtime_control, "strategy_type")
            == StrategyType.PINBAR_ENGULFING_EMA_RSI
        )
        assert getattr(provider.runtime_control, "interval") == Interval.M15
        assert provider.settings.strategy.strategy_interval is Interval.M15
        assert provider.settings.strategy.strategy_interval_source == "PIER_INTERVAL"
    finally:
        await provider.close()
