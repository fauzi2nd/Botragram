"""Regressions ensuring Telegram strategy messages contain valid HTML entities."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from botragram.constants.telegram import (
    DEFAULT_PARSE_MODE,
    MENU_STRATEGY,
)
from botragram.enums import ExecutionPolicy, Interval, StrategyType
from botragram.telegram.commands import strategy_command
from botragram.telegram.context import (
    ALLOWED_CHAT_IDS_KEY,
    BOT_CONTEXT_KEY,
    BotContext,
)
from botragram.telegram.messages import get_strategy_message
from botragram.telegram.runtime_menu_refresh import (
    menu_message_handler_with_runtime_refresh,
)
from botragram.telegram.strategy_switch import (
    strategy_switch_callback,
    strategy_switch_command,
)

_CHAT_ID = 12345
_RAW_AMPERSAND_PATTERN = re.compile(r"&(?!amp;|lt;|gt;|quot;|#\d+;)")


@dataclass(slots=True)
class _MockMessage:
    text: str = ""
    replies: list[str] = field(default_factory=list[str])
    parse_modes: list[str | None] = field(default_factory=list[str | None])
    reply_markups: list[object | None] = field(default_factory=list[object | None])

    async def reply_text(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: object | None = None,
    ) -> None:
        self.replies.append(text)
        self.parse_modes.append(parse_mode)
        self.reply_markups.append(reply_markup)


@dataclass(slots=True, frozen=True)
class _MockChat:
    id: int


@dataclass(slots=True)
class _MockCallbackQuery:
    data: str = ""
    answered: bool = False
    edited_text: str | None = None
    edited_parse_mode: str | None = None

    async def answer(self, *args: object, **kwargs: object) -> None:
        self.answered = True

    async def edit_message_text(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: object | None = None,
    ) -> None:
        self.edited_text = text
        self.edited_parse_mode = parse_mode


@dataclass(slots=True)
class _MockUpdate:
    message: _MockMessage | None = None
    effective_chat: _MockChat = field(default_factory=lambda: _MockChat(_CHAT_ID))
    callback_query: _MockCallbackQuery | None = None


@dataclass(slots=True)
class _MockContext:
    bot_data: dict[str, object] = field(default_factory=dict[str, object])


def test_all_strategy_messages_have_valid_html_entities() -> None:
    """Ensure every StrategyType message has zero raw unescaped ampersands."""
    for strategy in StrategyType:
        msg = get_strategy_message(
            strategy.value,
            9,
            21,
            confirmed=True,
            active_interval=Interval.M5,
            stop_loss_pct=Decimal("0.02"),
            take_profit_pct=Decimal("0.04"),
            risk_reward_ratio=Decimal("2.0"),
        )
        assert msg, f"Empty message for strategy {strategy.value}"
        unexpanded = _RAW_AMPERSAND_PATTERN.findall(msg)
        assert not unexpanded, (
            f"Strategy '{strategy.value}' has raw ampersand in HTML: {msg}"
        )


@pytest.mark.asyncio
async def test_strategy_switch_command_responds_for_botragram_origin() -> None:
    """Verify strategy_switch_command sends strategy menu for botragram_origin."""
    bot_context = BotContext(
        is_running=True,
        strategy_name=StrategyType.BOTRAGRAM_ORIGIN.value,
    )
    message = _MockMessage(text="/strategy")
    update = _MockUpdate(
        message=message,
        effective_chat=_MockChat(_CHAT_ID),
    )
    context = _MockContext(
        bot_data={
            BOT_CONTEXT_KEY: bot_context,
            ALLOWED_CHAT_IDS_KEY: frozenset({_CHAT_ID}),
        }
    )

    await strategy_switch_command(
        update=update,  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
    )

    assert len(message.replies) == 1
    reply = message.replies[0]
    assert "Botragram Origin" in reply
    assert "&amp;" in reply or "&" not in reply
    assert not _RAW_AMPERSAND_PATTERN.findall(reply)
    assert message.parse_modes[0] == DEFAULT_PARSE_MODE
    assert message.reply_markups[0] is not None


@pytest.mark.asyncio
async def test_menu_message_handler_with_runtime_refresh_routes_menu_strategy() -> None:
    """Verify MENU_STRATEGY button routes to strategy_switch_command."""
    bot_context = BotContext(
        is_running=True,
        strategy_name=StrategyType.BOTRAGRAM_ORIGIN.value,
    )
    message = _MockMessage(text=MENU_STRATEGY)
    update = _MockUpdate(
        message=message,
        effective_chat=_MockChat(_CHAT_ID),
    )
    context = _MockContext(
        bot_data={
            BOT_CONTEXT_KEY: bot_context,
            ALLOWED_CHAT_IDS_KEY: frozenset({_CHAT_ID}),
        }
    )

    await menu_message_handler_with_runtime_refresh(
        update=update,  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
    )

    assert len(message.replies) == 1
    reply = message.replies[0]
    assert "Botragram Origin" in reply
    assert not _RAW_AMPERSAND_PATTERN.findall(reply)


@pytest.mark.asyncio
async def test_strategy_switch_command_fallback_on_parse_error() -> None:
    """Fallback to plain send when Telegram raises a BadRequest on parse_mode."""
    bot_context = BotContext(
        is_running=True,
        strategy_name=StrategyType.BOTRAGRAM_ORIGIN.value,
    )

    mock_message = AsyncMock()
    # First call with parse_mode raises, second call succeeds
    mock_message.reply_text.side_effect = [
        RuntimeError("Bad Request: can't parse entities"),
        None,
    ]

    update = _MockUpdate(
        message=mock_message,
        effective_chat=_MockChat(_CHAT_ID),
    )
    context = _MockContext(
        bot_data={
            BOT_CONTEXT_KEY: bot_context,
            ALLOWED_CHAT_IDS_KEY: frozenset({_CHAT_ID}),
        }
    )

    await strategy_switch_command(
        update=update,  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
    )

    assert mock_message.reply_text.call_count == 2
    # Second call should not include parse_mode
    _, second_kwargs = mock_message.reply_text.call_args_list[1]
    assert "parse_mode" not in second_kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("action_text", ["Strategy", "🧠 Strategy ", "/strategy"])
async def test_menu_message_handler_lenient_strategy_aliases(action_text: str) -> None:
    """Ensure strategy menu triggers even if user sends plain or padded text."""
    bot_context = BotContext(
        is_running=True,
        strategy_name=StrategyType.BOTRAGRAM_ORIGIN.value,
    )
    message = _MockMessage(text=action_text)
    update = _MockUpdate(
        message=message,
        effective_chat=_MockChat(_CHAT_ID),
    )
    context = _MockContext(
        bot_data={
            BOT_CONTEXT_KEY: bot_context,
            ALLOWED_CHAT_IDS_KEY: frozenset({_CHAT_ID}),
        }
    )

    await menu_message_handler_with_runtime_refresh(
        update=update,  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
    )

    assert len(message.replies) == 1
    assert "Botragram Origin" in message.replies[0]


@pytest.mark.asyncio
async def test_strategy_switch_callback_answers_and_edits() -> None:
    """Ensure tapping cb_strategy calls query.answer() and edits message."""
    bot_context = BotContext(
        is_running=True,
        strategy_name=StrategyType.BOTRAGRAM_ORIGIN.value,
    )
    query = _MockCallbackQuery(data="cb_strategy")
    update = _MockUpdate(
        effective_chat=_MockChat(_CHAT_ID),
        callback_query=query,
    )
    context = _MockContext(
        bot_data={
            BOT_CONTEXT_KEY: bot_context,
            ALLOWED_CHAT_IDS_KEY: frozenset({_CHAT_ID}),
        }
    )

    await strategy_switch_callback(
        update=update,  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
    )

    assert query.answered is True
    assert query.edited_text is not None
    assert "Botragram Origin" in query.edited_text
    assert not _RAW_AMPERSAND_PATTERN.findall(query.edited_text)


@pytest.mark.asyncio
async def test_strategy_command_in_commands_module() -> None:
    """Verify strategy_command in commands module formats and responds cleanly."""
    bot_context = BotContext(
        is_running=True,
        execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
        strategy_name=StrategyType.BOTRAGRAM_ORIGIN.value,
    )
    message = _MockMessage(text="🧠 Strategy")
    update = _MockUpdate(
        message=message,
        effective_chat=_MockChat(_CHAT_ID),
    )
    context = _MockContext(
        bot_data={
            BOT_CONTEXT_KEY: bot_context,
            ALLOWED_CHAT_IDS_KEY: frozenset({_CHAT_ID}),
        }
    )

    await strategy_command(
        update=update,  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
    )

    assert len(message.replies) == 1
    assert "Botragram Origin" in message.replies[0]
    assert not _RAW_AMPERSAND_PATTERN.findall(message.replies[0])


class _MockMultiContextControl:
    @property
    def interval(self) -> Interval:
        raise RuntimeError(
            "Singular runtime configuration is unavailable for multiple "
            "runtime contexts"
        )

    @property
    def configured_strategy_type(self) -> StrategyType:
        return StrategyType.BOTRAGRAM_ORIGIN


def test_active_interval_multi_context_fallback() -> None:
    """Ensure active_interval falls back to configured_interval on multi-context."""
    bot_context = BotContext(
        configured_interval=Interval.M5,
        runtime_control=_MockMultiContextControl(),  # type: ignore[arg-type]
    )
    assert bot_context.active_interval == Interval.M5


@pytest.mark.asyncio
async def test_strategy_switch_command_multi_context_autonomous_live() -> None:
    """Ensure strategy_switch_command formats full message in multi-context mode."""
    bot_context = BotContext(
        is_running=True,
        execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
        strategy_name=StrategyType.BOTRAGRAM_ORIGIN.value,
        configured_interval=Interval.M3,
        runtime_control=_MockMultiContextControl(),  # type: ignore[arg-type]
    )
    message = _MockMessage(text="🧠 Strategy")
    update = _MockUpdate(
        message=message,
        effective_chat=_MockChat(_CHAT_ID),
    )
    context = _MockContext(
        bot_data={
            BOT_CONTEXT_KEY: bot_context,
            ALLOWED_CHAT_IDS_KEY: frozenset({_CHAT_ID}),
        }
    )

    await strategy_switch_command(
        update=update,  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
    )

    assert len(message.replies) == 1
    assert "Botragram Origin" in message.replies[0]
    assert "Timeframe:" in message.replies[0]
    assert message.parse_modes[0] == DEFAULT_PARSE_MODE
