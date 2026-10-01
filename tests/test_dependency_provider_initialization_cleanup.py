"""Dependency-provider startup resource cleanup regressions."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from botragram.app import DependencyProvider
from botragram.config import Settings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.enums import ExchangeType
from botragram.storage.sqlite import SQLiteDatabase, SQLiteMigrationManager
from botragram.telegram import TelegramBot


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


@pytest.mark.asyncio
@pytest.mark.usefixtures("stub_binance_time_sync")
async def test_telegram_startup_failure_schedules_reconnect_after_initialization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep trading dependencies available and reconnect only after startup."""
    start_with_retry = AsyncMock(side_effect=RuntimeError("telegram unavailable"))
    reconnect_started = AsyncMock()
    monkeypatch.setattr(TelegramBot, "start_with_retry", start_with_retry)
    monkeypatch.setattr(TelegramBot, "start", reconnect_started)
    provider = DependencyProvider(
        database_path=tmp_path / "botragram.db",
        settings=Settings(exchange=ExchangeSettings(exchange=ExchangeType.BINANCE)),
    )
    try:
        await provider.initialize()
        assert provider.is_initialized
        reconnect_task = next(
            task
            for task in asyncio.all_tasks()
            if task.get_name() == "telegram-reconnect-loop"
        )
        assert not reconnect_task.done()
        start_with_retry.assert_awaited_once()
    finally:
        await provider.close()

    assert reconnect_task.done()
    reconnect_started.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.usefixtures("stub_binance_time_sync")
async def test_telegram_reconnect_retries_after_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Retry Telegram in the background without interrupting provider startup."""
    started = asyncio.Event()

    async def reconnect(bot: TelegramBot) -> None:
        del bot
        started.set()

    refresh = AsyncMock()
    monkeypatch.setattr(
        TelegramBot,
        "start_with_retry",
        AsyncMock(side_effect=RuntimeError("telegram unavailable")),
    )
    monkeypatch.setattr(TelegramBot, "start", reconnect)
    monkeypatch.setattr(TelegramBot, "publish_home_menu_refresh", refresh)
    provider = DependencyProvider(
        database_path=tmp_path / "botragram.db",
        settings=Settings(exchange=ExchangeSettings(exchange=ExchangeType.BINANCE)),
    )
    try:
        await provider.initialize()
        await asyncio.wait_for(started.wait(), timeout=6.0)
        await asyncio.sleep(0)
        assert provider.is_initialized
        refresh.assert_awaited_once()
    finally:
        await provider.close()
