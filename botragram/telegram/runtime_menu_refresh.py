"""Refresh Telegram runtime controls after pause or resume actions."""

from __future__ import annotations

from typing import Final

from telegram import Update
from telegram.ext import ContextTypes

from botragram.constants.telegram import (
    DEFAULT_PARSE_MODE,
    MENU_PAUSE,
    MENU_RESUME,
    MENU_START,
)
from botragram.telegram.access import is_authorized_update
from botragram.telegram.commands import (
    menu_message_handler,
    pause_bot_command,
    start_bot_command,
)
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext
from botragram.telegram.keyboards import get_main_menu_keyboard

_REFRESH_MESSAGE: Final[str] = "🔄 <b>Menu runtime diperbarui.</b>"
_RUNTIME_MENU_ACTIONS: Final[frozenset[str]] = frozenset(
    {MENU_START, MENU_RESUME, MENU_PAUSE}
)


def _get_bot_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext | None:
    """Return the active Telegram context when composition has installed it."""
    candidate = context.bot_data.get(BOT_CONTEXT_KEY)
    return candidate if isinstance(candidate, BotContext) else None


async def _refresh_runtime_menu(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Publish a keyboard derived from the authoritative current runtime state."""
    if update.message is None:
        return
    if not is_authorized_update(update=update, context=context):
        return

    bot_context = _get_bot_context(context)
    if bot_context is None:
        return

    control = bot_context.runtime_control
    await update.message.reply_text(
        _REFRESH_MESSAGE,
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=get_main_menu_keyboard(
            execution_policy=bot_context.execution_policy,
            is_paused=control.is_paused if control is not None else True,
        ),
    )


async def start_bot_command_with_menu_refresh(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Resume trading and immediately publish the refreshed persistent menu."""
    await start_bot_command(update, context)
    await _refresh_runtime_menu(update=update, context=context)


async def pause_bot_command_with_menu_refresh(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Pause trading and immediately publish the refreshed persistent menu."""
    await pause_bot_command(update, context)
    await _refresh_runtime_menu(update=update, context=context)


async def menu_message_handler_with_runtime_refresh(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Delegate normal menu routing and refresh only runtime state transitions."""
    action = update.message.text if update.message is not None else None
    await menu_message_handler(update, context)
    if action in _RUNTIME_MENU_ACTIONS:
        await _refresh_runtime_menu(update=update, context=context)
