"""Runtime pause/resume persistent-menu refresh regressions."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from telegram import ReplyKeyboardMarkup

import botragram.telegram.runtime_menu_refresh as refresh_module
from botragram.app import TradingRuntimeControl
from botragram.constants.telegram import MENU_PAUSE, MENU_RESUME
from botragram.enums import ExecutionPolicy
from botragram.telegram.context import (
    ALLOWED_CHAT_IDS_KEY,
    BOT_CONTEXT_KEY,
    BotContext,
)

_CHAT_ID = 12345


@dataclass(slots=True)
class _FakeMessage:
    """Capture replies and persistent-keyboard updates."""

    text: str = ""
    reply_markups: list[object | None] = field(default_factory=list[object | None])

    async def reply_text(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: object | None = None,
    ) -> None:
        """Capture one response without depending on Telegram network I/O."""
        del text, parse_mode
        self.reply_markups.append(reply_markup)


@dataclass(slots=True, frozen=True)
class _FakeChat:
    """Expose the allow-listed chat identity used by access control."""

    id: int


@dataclass(slots=True)
class _FakeUpdate:
    """Provide the minimal update contract consumed by refresh handlers."""

    message: _FakeMessage
    effective_chat: _FakeChat


@dataclass(slots=True)
class _FakeContext:
    """Provide Telegram bot_data for runtime menu derivation."""

    bot_data: dict[str, object]


def _labels(markup: object | None) -> set[str]:
    """Return every label from one captured persistent reply keyboard."""
    assert isinstance(markup, ReplyKeyboardMarkup)
    return {button.text for row in markup.keyboard for button in row}


def _context(runtime_control: TradingRuntimeControl) -> _FakeContext:
    """Build one authorized autonomous-LIVE Telegram context."""
    return _FakeContext(
        bot_data={
            ALLOWED_CHAT_IDS_KEY: frozenset({_CHAT_ID}),
            BOT_CONTEXT_KEY: BotContext(
                execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
                runtime_control=runtime_control,
            ),
        }
    )


@pytest.mark.asyncio
async def test_pause_command_refreshes_menu_to_resume_without_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish Resume immediately after an acknowledged runtime pause."""
    runtime_control = TradingRuntimeControl()
    assert runtime_control.resume_global_cycle()
    update = _FakeUpdate(message=_FakeMessage(), effective_chat=_FakeChat(_CHAT_ID))
    context = _context(runtime_control)

    async def pause_runtime(update: object, context: object) -> None:
        del update, context
        assert runtime_control.pause()

    monkeypatch.setattr(refresh_module, "pause_bot_command", pause_runtime)

    await refresh_module.pause_bot_command_with_menu_refresh(update, context)  # type: ignore[arg-type]

    assert runtime_control.is_paused
    labels = _labels(update.message.reply_markups[-1])
    assert MENU_RESUME in labels
    assert MENU_PAUSE not in labels


@pytest.mark.asyncio
async def test_resume_command_refreshes_menu_to_pause_without_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish Pause immediately after an acknowledged runtime resume."""
    runtime_control = TradingRuntimeControl()
    update = _FakeUpdate(message=_FakeMessage(), effective_chat=_FakeChat(_CHAT_ID))
    context = _context(runtime_control)

    async def resume_runtime(update: object, context: object) -> None:
        del update, context
        assert runtime_control.resume_global_cycle()

    monkeypatch.setattr(refresh_module, "start_bot_command", resume_runtime)

    await refresh_module.start_bot_command_with_menu_refresh(update, context)  # type: ignore[arg-type]

    assert not runtime_control.is_paused
    labels = _labels(update.message.reply_markups[-1])
    assert MENU_PAUSE in labels
    assert MENU_RESUME not in labels


@pytest.mark.asyncio
async def test_pause_menu_button_refreshes_persistent_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh a reply-keyboard Pause action without requiring slash commands."""
    runtime_control = TradingRuntimeControl()
    assert runtime_control.resume_global_cycle()
    update = _FakeUpdate(
        message=_FakeMessage(text=MENU_PAUSE),
        effective_chat=_FakeChat(_CHAT_ID),
    )
    context = _context(runtime_control)

    async def route_pause(update: object, context: object) -> None:
        del update, context
        assert runtime_control.pause()

    monkeypatch.setattr(refresh_module, "menu_message_handler", route_pause)

    await refresh_module.menu_message_handler_with_runtime_refresh(  # type: ignore[arg-type]
        update,
        context,
    )

    labels = _labels(update.message.reply_markups[-1])
    assert MENU_RESUME in labels
    assert MENU_PAUSE not in labels
