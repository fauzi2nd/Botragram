"""
Botragram

Description:
    Regression tests for Telegram bot resilience, timeouts, and background reconnection.

Python:
    3.14+
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Self

import pytest

from botragram.config.telegram_settings import TelegramSettings
from botragram.enums import AuthorizationStatus, NotificationType, SignalType
from botragram.models import ExecutionAuthorization, Notification, Signal
from botragram.telegram.bot import TelegramBot
from botragram.telegram.context import BotContext


def _noop_register_handlers(_app: object) -> None:
    """No-op stub for handler registration in unit tests."""
    del _app


@dataclass(slots=True)
class _FakeBotApi:
    """Simulate transient failures on Telegram Bot API."""

    fail_count: int = 0
    attempts: int = 0
    sent_messages: list[dict[str, object]] = field(
        default_factory=list[dict[str, object]]
    )

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: object = None,
    ) -> None:
        """Deliver one message or fail if fail_count > 0."""
        self.attempts += 1
        if self.fail_count > 0:
            self.fail_count -= 1
            raise TimeoutError("Simulated Telegram connection timeout")
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )

    async def set_my_commands(self, commands: object) -> bool:
        """Stub for set_my_commands."""
        del commands
        return True


@dataclass(slots=True)
class _FakeApplication:
    """Mock Telegram application containing fake bot API."""

    bot: _FakeBotApi
    updater: object = None
    bot_data: dict[str, object] = field(default_factory=dict[str, object])
    fail_initialize_count: int = 0
    initialize_attempts: int = 0

    async def initialize(self) -> None:
        self.initialize_attempts += 1
        if self.fail_initialize_count > 0:
            self.fail_initialize_count -= 1
            raise TimeoutError("Simulated initialize timeout")

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


@dataclass(slots=True)
class _FakeBuilder:
    """Mock ApplicationBuilder."""

    app: _FakeApplication

    def token(self, token: str) -> Self:
        del token
        return self

    def request(self, request: object) -> Self:
        del request
        return self

    def build(self) -> _FakeApplication:
        return self.app


@pytest.mark.asyncio
async def test_telegram_bot_publish_retries_and_succeeds_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TelegramBot retries delivery on transient network timeout and succeeds."""
    fake_api = _FakeBotApi(fail_count=1)
    fake_app = _FakeApplication(bot=fake_api)

    monkeypatch.setattr(
        "botragram.telegram.bot.ApplicationBuilder",
        lambda: _FakeBuilder(app=fake_app),
    )
    monkeypatch.setattr(
        "botragram.telegram.bot.register_handlers",
        _noop_register_handlers,
    )

    settings = TelegramSettings(
        enabled=True,
        bot_token="test_token",
        allowed_chat_ids=[123456],
    )
    bot = TelegramBot(settings=settings, context=BotContext())
    await bot.start()

    notification = Notification(
        title="Trade Completed: BTCUSDT",
        message="Trade Completed (WIN)",
        level=NotificationType.INFO,
        created_at=datetime.now(UTC),
    )

    await bot.publish(notification=notification)

    # 1 fail + 1 success = 2 attempts
    assert fake_api.attempts == 2
    assert len(fake_api.sent_messages) == 1
    assert fake_api.sent_messages[0]["chat_id"] == 123456
    assert fake_api.sent_messages[0]["text"] == "Trade Completed (WIN)"


@pytest.mark.asyncio
async def test_telegram_bot_publish_fails_gracefully_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TelegramBot catches and logs exception after all retry attempts fail."""
    fake_api = _FakeBotApi(fail_count=5)  # Fails all attempts
    fake_app = _FakeApplication(bot=fake_api)

    monkeypatch.setattr(
        "botragram.telegram.bot.ApplicationBuilder",
        lambda: _FakeBuilder(app=fake_app),
    )
    monkeypatch.setattr(
        "botragram.telegram.bot.register_handlers",
        _noop_register_handlers,
    )

    settings = TelegramSettings(
        enabled=True,
        bot_token="test_token",
        allowed_chat_ids=[123456],
    )
    bot = TelegramBot(settings=settings, context=BotContext())
    await bot.start()

    notification = Notification(
        title="Trade Completed: BTCUSDT",
        message="Trade Completed (WIN)",
        level=NotificationType.INFO,
        created_at=datetime.now(UTC),
    )

    # Must not raise an unhandled exception
    await bot.publish(notification=notification)
    assert fake_api.attempts == 3
    assert len(fake_api.sent_messages) == 0


@pytest.mark.asyncio
async def test_telegram_bot_start_with_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TelegramBot start_with_retry succeeds after a transient boot failure."""
    fake_api = _FakeBotApi()
    fake_app = _FakeApplication(bot=fake_api, fail_initialize_count=1)

    monkeypatch.setattr(
        "botragram.telegram.bot.ApplicationBuilder",
        lambda: _FakeBuilder(app=fake_app),
    )
    monkeypatch.setattr(
        "botragram.telegram.bot.register_handlers",
        _noop_register_handlers,
    )

    settings = TelegramSettings(
        enabled=True,
        bot_token="test_token",
        allowed_chat_ids=[123456],
    )
    bot = TelegramBot(settings=settings, context=BotContext())

    await bot.start_with_retry(max_attempts=3, delay_seconds=0.01)
    assert bot.is_running
    assert fake_app.initialize_attempts == 2


@pytest.mark.asyncio
async def test_telegram_bot_publish_execution_authorization_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execution authorization notifications also retry on transient errors."""
    fake_api = _FakeBotApi(fail_count=1)
    fake_app = _FakeApplication(bot=fake_api)

    monkeypatch.setattr(
        "botragram.telegram.bot.ApplicationBuilder",
        lambda: _FakeBuilder(app=fake_app),
    )
    monkeypatch.setattr(
        "botragram.telegram.bot.register_handlers",
        _noop_register_handlers,
    )

    settings = TelegramSettings(
        enabled=True,
        bot_token="test_token",
        allowed_chat_ids=[123456],
    )
    bot = TelegramBot(settings=settings, context=BotContext())
    await bot.start()

    now = datetime.now(UTC)
    auth = ExecutionAuthorization(
        authorization_id="12345678123456781234567812345678",
        signal=Signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100"),
            confidence=Decimal("0.8"),
            strategy_name="EMA_CROSS",
            generated_at=now,
            reason="Test signal",
        ),
        status=AuthorizationStatus.PENDING,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )

    await bot.publish_execution_authorization(authorization=auth)
    assert fake_api.attempts == 2
    assert len(fake_api.sent_messages) == 1
