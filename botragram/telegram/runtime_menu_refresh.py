"""Refresh Telegram runtime controls in the pause/resume action response."""

from __future__ import annotations

import logging
from html import escape
from typing import Final

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from botragram.constants.telegram import (
    DEFAULT_PARSE_MODE,
    MENU_PAUSE,
    MENU_RESUME,
    MENU_START,
    MENU_STRATEGY,
)
from botragram.telegram.access import is_authorized_update
from botragram.telegram.commands import menu_message_handler
from botragram.telegram.context import (
    BOT_CONTEXT_KEY,
    MARKET_SEARCH_PENDING_KEY,
    BotContext,
)
from botragram.telegram.keyboards import get_main_menu_keyboard
from botragram.telegram.messages import (
    get_resume_message,
    get_runtime_pause_message,
    get_startup_configuration_message,
)
from botragram.telegram.strategy_switch import strategy_switch_command

logger: Final[logging.Logger] = logging.getLogger(__name__)
_DATA_UNAVAILABLE_MESSAGE: Final[str] = (
    "⚠️ <b>Data sementara tidak tersedia.</b> Silakan coba lagi."
)


def _get_bot_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    """Return the active BotContext or a safe default context."""
    candidate = context.bot_data.get(BOT_CONTEXT_KEY)
    return candidate if isinstance(candidate, BotContext) else BotContext()


def _get_runtime_menu_keyboard(bot_context: BotContext) -> ReplyKeyboardMarkup:
    """Derive the persistent menu from authoritative runtime pause state."""
    control = bot_context.runtime_control
    return get_main_menu_keyboard(
        execution_policy=bot_context.execution_policy,
        is_paused=control.is_paused if control is not None else True,
    )


def _get_runtime_startup_checklist(bot_context: BotContext) -> str:
    """Return the current startup checklist for non-discovery workflows."""
    control = bot_context.runtime_control
    if control is None:
        return ""
    return get_startup_configuration_message(
        exchange=bot_context.exchange_type,
        market_type=control.market_type.value,
        symbol=control.symbol,
        interval=control.interval.value,
        strategy=control.strategy_type.value,
        missing_requirements=control.get_missing_startup_requirements(),
    )


async def _reply_data_unavailable(update: Update) -> None:
    """Send the standard Telegram unavailable-data response."""
    if update.message is None:
        return
    await update.message.reply_text(
        _DATA_UNAVAILABLE_MESSAGE,
        parse_mode=DEFAULT_PARSE_MODE,
    )


async def _resume_autonomous_live(bot_context: BotContext) -> bool:
    """Resume autonomous LIVE only from a reconciled fail-closed runtime state."""
    control = bot_context.runtime_control
    provider = bot_context.query_provider
    if control is None or provider is None:
        raise RuntimeError("Autonomous LIVE runtime observability is unavailable")

    recovery = await provider.get_autonomous_live_recovery()
    if recovery is None:
        raise RuntimeError("Autonomous LIVE recovery state is unavailable")
    if recovery.new_entry_blocked_by_recovery:
        raise RuntimeError("Autonomous LIVE recovery is incomplete")

    positions = tuple(await provider.get_positions())
    runtime_contexts = control.runtime_contexts
    managed_symbols = {runtime_context.symbol for runtime_context in runtime_contexts}
    position_symbols = {position.symbol for position in positions}

    if runtime_contexts:
        if managed_symbols != position_symbols:
            raise RuntimeError("LIVE portfolio requires reconciliation before resume")
        return control.resume()

    if positions:
        raise RuntimeError("Unmanaged LIVE positions require recovery before resume")
    if not recovery.autonomous_entry_authorized:
        raise RuntimeError("Autonomous LIVE entry is not authorized")

    return control.resume_global_cycle()


async def start_bot_command_with_menu_refresh(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Resume trading and attach the refreshed menu to the same response."""
    if update.message is None:
        return
    if not is_authorized_update(update=update, context=context):
        return

    bot_context = _get_bot_context(context)
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
            checklist = _get_runtime_startup_checklist(bot_context)
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
        reply_markup=_get_runtime_menu_keyboard(bot_context),
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

    bot_context = _get_bot_context(context)
    control = bot_context.runtime_control
    if control is None:
        await _reply_data_unavailable(update)
        return

    message = get_runtime_pause_message(changed=control.pause())
    await update.message.reply_text(
        message,
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=_get_runtime_menu_keyboard(bot_context),
    )


async def menu_message_handler_with_runtime_refresh(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Route runtime buttons through single-response menu-refresh handlers."""
    if update.message is None:
        return

    action = update.message.text or ""
    if action == MENU_STRATEGY:
        await strategy_switch_command(update, context)
        return
    if action not in {MENU_START, MENU_RESUME, MENU_PAUSE}:
        await menu_message_handler(update, context)
        return

    if not is_authorized_update(update=update, context=context):
        return

    bot_context = _get_bot_context(context)
    if action == MENU_START and bot_context.is_discovery_workflow:
        await menu_message_handler(update, context)
        return

    if context.chat_data is not None:
        context.chat_data.pop(MARKET_SEARCH_PENDING_KEY, None)

    if action == MENU_PAUSE:
        await pause_bot_command_with_menu_refresh(update, context)
        return

    await start_bot_command_with_menu_refresh(update, context)
