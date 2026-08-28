"""Refresh Telegram runtime controls in the pause/resume action response."""

from __future__ import annotations

import logging
from html import escape
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
    _get_context,
    _get_context_main_menu_keyboard,
    _get_startup_configuration_message,
    _reply_data_unavailable,
    _resume_autonomous_live,
    menu_message_handler,
)
from botragram.telegram.context import MARKET_SEARCH_PENDING_KEY
from botragram.telegram.messages import get_resume_message, get_runtime_pause_message

logger: Final[logging.Logger] = logging.getLogger(__name__)


async def start_bot_command_with_menu_refresh(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Resume trading and attach the refreshed menu to the same response."""
    if update.message is None:
        return
    if not is_authorized_update(update=update, context=context):
        return

    bot_context = _get_context(context)
    control = bot_context.runtime_control
    if control is None:
        await _reply_data_unavailable(update)
        return

    try:
        changed = (
            await _resume_autonomous_live(bot_context)
            if bot_context.is_autonomous_live
            else control.resume()
        )
        message = get_resume_message(changed=changed)
    except RuntimeError as error:
        if bot_context.is_autonomous_live:
            message = (
                "⚠️ <b>Autonomous LIVE belum dapat dilanjutkan.</b>\n"
                f"<code>{escape(str(error))}</code>"
            )
        else:
            checklist = _get_startup_configuration_message(bot_context)
            message = f"⚠️ <b>Trading belum dapat dimulai.</b>\n\n{checklist}"
    except Exception:
        logger.exception("Autonomous LIVE resume verification failed")
        message = (
            "⚠️ <b>Autonomous LIVE belum dapat dilanjutkan.</b> "
            "Runtime state tidak tersedia."
        )

    await update.message.reply_text(
        message,
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=_get_context_main_menu_keyboard(bot_context),
    )


async def pause_bot_command_with_menu_refresh(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Pause trading and attach the refreshed menu to the same response."""
    if update.message is None:
        return
    if not is_authorized_update(update=update, context=context):
        return

    bot_context = _get_context(context)
    control = bot_context.runtime_control
    if control is None:
        await _reply_data_unavailable(update)
        return

    message = get_runtime_pause_message(changed=control.pause())
    await update.message.reply_text(
        message,
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=_get_context_main_menu_keyboard(bot_context),
    )


async def menu_message_handler_with_runtime_refresh(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Route runtime buttons through single-response menu-refresh handlers."""
    if update.message is None:
        return

    action = update.message.text or ""
    if action not in {MENU_START, MENU_RESUME, MENU_PAUSE}:
        await menu_message_handler(update, context)
        return

    if not is_authorized_update(update=update, context=context):
        return

    bot_context = _get_context(context)
    if action == MENU_START and bot_context.is_discovery_workflow:
        await menu_message_handler(update, context)
        return

    if context.chat_data is not None:
        context.chat_data.pop(MARKET_SEARCH_PENDING_KEY, None)

    if action == MENU_PAUSE:
        await pause_bot_command_with_menu_refresh(update, context)
        return

    await start_bot_command_with_menu_refresh(update, context)
