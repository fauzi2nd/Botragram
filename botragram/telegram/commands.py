"""
Botragram

Description:
    Telegram bot command handlers.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
import logging

# =============================================================================
# Third Party
# =============================================================================
from telegram import Update
from telegram.ext import ContextTypes

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import DEFAULT_PARSE_MODE
from botragram.telegram.context import BotContext
from botragram.telegram.keyboards import get_exchange_keyboard, get_main_menu_keyboard
from botragram.telegram.messages import (
    get_exchange_message,
    get_positions_message,
    get_settings_message,
    get_status_message,
    get_welcome_message,
)

logger = logging.getLogger(__name__)

# Key used to store BotContext inside telegram bot_data
BOT_CONTEXT_KEY: str = "bot_context"


def _get_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    """Retrieve BotContext from Telegram bot_data.

    Args:
        context: Telegram callback context.

    Returns:
        BotContext instance, or a fresh default if not set.
    """
    ctx = context.bot_data.get(BOT_CONTEXT_KEY)
    if isinstance(ctx, BotContext):
        return ctx
    return BotContext()


# =============================================================================
# Command Handlers
# =============================================================================
async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /start command.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    if update.message:
        msg = get_welcome_message()
        kb = get_main_menu_keyboard()
        await update.message.reply_text(
            msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=kb
        )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /status command.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    if update.message:
        ctx = _get_context(context)
        msg = get_status_message(
            is_running=ctx.is_running,
            trade_mode=ctx.trade_mode,
            symbol=ctx.symbol,
            last_price=ctx.last_price,
        )
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def positions_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /positions command.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    if update.message:
        ctx = _get_context(context)
        msg = get_positions_message(ctx.positions)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def settings_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /settings command.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    if update.message:
        ctx = _get_context(context)
        msg = get_settings_message(
            exchange_type=ctx.exchange_type,
            strategy_name=ctx.strategy_name,
            trade_mode=ctx.trade_mode,
        )
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def exchange_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /exchange command — show exchange selection keyboard.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    if update.message:
        ctx = _get_context(context)
        msg = get_exchange_message(ctx.exchange_type)
        kb = get_exchange_keyboard(ctx.exchange_type)
        await update.message.reply_text(
            msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=kb
        )
