"""Execution-policy restart persistent-menu refresh regressions."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Self

import pytest
from telegram import BotCommand, ReplyKeyboardMarkup

import botragram.telegram.bot as telegram_bot_module
from botragram.app import TradingRuntimeControl, prepare_restarted_runtime_session
from botragram.config.telegram_settings import TelegramSettings
from botragram.constants.telegram import (
    MENU_CONFIGURATION,
    MENU_RESUME,
    MENU_RISK_LIMITS,
    MENU_TRADING,
    MENU_TRADING_MODE,
)
from botragram.enums import ExecutionPolicy, MarketType
from botragram.telegram import TelegramBot
from botragram.telegram.context import BotContext

_CHAT_ID = 12345
_SWITCHED_MESSAGE = "Trading Mode Switched"


@dataclass(slots=True, kw_only=True, frozen=True)
class _SentMessage:
    """Capture one outbound Telegram message."""

    chat_id: int
    text: str
    parse_mode: str
    reply_markup: ReplyKeyboardMarkup


@dataclass(slots=True, kw_only=True)
class _FakeTelegramApi:
    """Capture outbound Bot API calls without network access."""

    fail_delivery: bool = False
    commands: tuple[BotCommand, ...] = ()
    messages: list[_SentMessage] = field(default_factory=list[_SentMessage])

    async def set_my_commands(self, commands: Sequence[BotCommand]) -> None:
        """Capture the command registration."""
        self.commands = tuple(commands)

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        parse_mode: str,
        reply_markup: ReplyKeyboardMarkup,
    ) -> None:
        """Capture one mode-switch message or simulate delivery failure."""
        if self.fail_delivery:
            raise RuntimeError("configured Telegram delivery failure")
        self.messages.append(
            _SentMessage(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        )


@dataclass(slots=True)
class _FakeUpdater:
    """Provide the polling lifecycle consumed by TelegramBot."""

    running: bool = False

    async def start_polling(self) -> None:
        """Mark polling active."""
        self.running = True

    async def stop(self) -> None:
        """Mark polling inactive."""
        self.running = False


@dataclass(slots=True, kw_only=True)
class _FakeTelegramApplication:
    """Provide the minimal python-telegram-bot application contract."""

    bot: _FakeTelegramApi
    bot_data: dict[str, object] = field(default_factory=dict[str, object])
    updater: _FakeUpdater = field(default_factory=_FakeUpdater)
    initialized: bool = False
    started: bool = False

    async def initialize(self) -> None:
        """Mark the fake application initialized."""
        self.initialized = True

    async def start(self) -> None:
        """Mark the fake application started."""
        self.started = True

    async def stop(self) -> None:
        """Mark the fake application stopped."""
        self.started = False

    async def shutdown(self) -> None:
        """Mark the fake application uninitialized."""
        self.initialized = False


@dataclass(slots=True, kw_only=True)
class _FakeApplicationBuilder:
    """Build one configured fake Telegram application."""

    application: _FakeTelegramApplication
    token_value: str = ""

    def token(self, token: str) -> Self:
        """Capture the configured bot token."""
        self.token_value = token
        return self

    def build(self) -> _FakeTelegramApplication:
        """Return the configured fake application."""
        return self.application


def _ignore_handler_registration(application: object) -> None:
    """Keep adapter tests independent from Telegram handler internals."""
    del application


async def _start_bot(
    *,
    monkeypatch: pytest.MonkeyPatch,
    context: BotContext,
    fail_delivery: bool = False,
) -> tuple[TelegramBot, _FakeTelegramApi]:
    """Start TelegramBot against a deterministic in-memory Bot API."""
    api = _FakeTelegramApi(fail_delivery=fail_delivery)
    application = _FakeTelegramApplication(bot=api)

    def build_application() -> _FakeApplicationBuilder:
        return _FakeApplicationBuilder(application=application)

    monkeypatch.setattr(telegram_bot_module, "ApplicationBuilder", build_application)
    monkeypatch.setattr(
        telegram_bot_module,
        "register_handlers",
        _ignore_handler_registration,
    )
    bot = TelegramBot(
        settings=TelegramSettings(
            enabled=True,
            bot_token="test-token",
            allowed_chat_ids=[_CHAT_ID],
        ),
        context=context,
    )
    await bot.start()
    return bot, api


def _labels(markup: ReplyKeyboardMarkup) -> set[str]:
    """Return every text label in one persistent reply keyboard."""
    return {button.text for row in markup.keyboard for button in row}


@pytest.mark.asyncio
async def test_single_symbol_restart_publishes_new_home_menu_without_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish the SINGLE_SYMBOL keyboard from the initialized new BotContext."""
    runtime_control = TradingRuntimeControl()
    assert runtime_control.resume_global_cycle()
    bot, api = await _start_bot(
        monkeypatch=monkeypatch,
        context=BotContext(
            execution_policy=ExecutionPolicy.SINGLE_SYMBOL,
            runtime_control=runtime_control,
        ),
    )
    try:
        await prepare_restarted_runtime_session(
            restart_target=ExecutionPolicy.SINGLE_SYMBOL,
            runtime_control=runtime_control,
            home_menu_publisher=bot,
        )
    finally:
        await bot.stop()

    assert runtime_control.is_paused
    assert len(api.messages) == 1
    message = api.messages[0]
    labels = _labels(message.reply_markup)
    assert message.text == _SWITCHED_MESSAGE
    assert MENU_CONFIGURATION in labels
    assert MENU_TRADING in labels
    assert MENU_TRADING_MODE in labels
    assert MENU_RISK_LIMITS not in labels


@pytest.mark.asyncio
async def test_autonomous_live_restart_publishes_paused_resume_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish the AUTONOMOUS_LIVE menu with Resume after forcing PAUSED."""
    runtime_control = TradingRuntimeControl()
    assert runtime_control.resume_global_cycle()
    bot, api = await _start_bot(
        monkeypatch=monkeypatch,
        context=BotContext(
            execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
            runtime_control=runtime_control,
        ),
    )
    try:
        await prepare_restarted_runtime_session(
            restart_target=ExecutionPolicy.AUTONOMOUS_LIVE,
            runtime_control=runtime_control,
            home_menu_publisher=bot,
        )
    finally:
        await bot.stop()

    assert runtime_control.is_paused
    assert len(api.messages) == 1
    labels = _labels(api.messages[0].reply_markup)
    assert MENU_RESUME in labels
    assert MENU_RISK_LIMITS in labels
    assert MENU_TRADING_MODE in labels
    assert MENU_CONFIGURATION not in labels


@pytest.mark.parametrize(
    "restart_target",
    (None, MarketType.FUTURES),
    ids=("cold-startup", "market-type-restart"),
)
@pytest.mark.asyncio
async def test_non_policy_startup_does_not_refresh_or_change_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
    restart_target: MarketType | None,
) -> None:
    """Leave cold startup and MarketType restart behavior unchanged."""
    runtime_control = TradingRuntimeControl()
    assert runtime_control.resume_global_cycle()
    bot, api = await _start_bot(
        monkeypatch=monkeypatch,
        context=BotContext(runtime_control=runtime_control),
    )
    try:
        await prepare_restarted_runtime_session(
            restart_target=restart_target,
            runtime_control=runtime_control,
            home_menu_publisher=bot,
        )
    finally:
        await bot.stop()

    assert not runtime_control.is_paused
    assert api.messages == []


@pytest.mark.asyncio
async def test_mode_switch_refresh_delivery_failure_is_non_blocking(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log Telegram delivery failure without failing the restarted runtime."""
    runtime_control = TradingRuntimeControl()
    bot, _ = await _start_bot(
        monkeypatch=monkeypatch,
        context=BotContext(
            execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
            runtime_control=runtime_control,
        ),
        fail_delivery=True,
    )
    caplog.set_level(logging.ERROR, logger=telegram_bot_module.__name__)
    try:
        await prepare_restarted_runtime_session(
            restart_target=ExecutionPolicy.AUTONOMOUS_LIVE,
            runtime_control=runtime_control,
            home_menu_publisher=bot,
        )
    finally:
        await bot.stop()

    assert runtime_control.is_paused
    assert "Telegram home-menu refresh delivery failed" in caplog.text
