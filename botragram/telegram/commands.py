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

import logging

# =============================================================================
# Standard Library
# =============================================================================
from decimal import Decimal

# =============================================================================
# Third Party
# =============================================================================
from telegram import Update
from telegram.ext import ContextTypes

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import (
    DEFAULT_PARSE_MODE,
    MENU_EXCHANGE,
    MENU_PAUSE,
    MENU_POSITIONS,
    MENU_SETTINGS,
    MENU_START,
    MENU_STATUS,
    MENU_STOP,
    MENU_STRATEGY,
    MENU_STREAM,
    MENU_TEST,
)
from botragram.telegram.context import BotContext
from botragram.telegram.keyboards import get_exchange_keyboard, get_main_menu_keyboard
from botragram.telegram.messages import (
    get_balance_message,
    get_exchange_message,
    get_history_message,
    get_market_message,
    get_orders_message,
    get_pause_message,
    get_positions_message,
    get_settings_message,
    get_start_message,
    get_status_message,
    get_strategy_message,
    get_stream_message,
    get_test_message,
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


async def market_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        ctx = _get_context(context)
        msg = get_market_message(ctx.symbol, ctx.last_price)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def orders_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        msg = get_orders_message(())
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        msg = get_balance_message(Decimal("0"))
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def history_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        msg = get_history_message()
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def strategy_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        ctx = _get_context(context)
        fast_period = 9
        slow_period = 21
        msg = get_strategy_message(ctx.strategy_name, fast_period, slow_period)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def stream_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        msg = get_stream_message()
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def start_bot_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        ctx = _get_context(context)
        msg = get_start_message(ctx.is_running)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def pause_bot_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        ctx = _get_context(context)
        msg = get_pause_message(ctx.is_running)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def test_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        msg = get_test_message()
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def menu_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle a selection from the persistent Telegram reply keyboard.

    Args:
        update: Incoming Telegram update.
        context: Telegram handler context.
    """
    if update.message is None:
        return

    action = update.message.text
    if action == MENU_STATUS:
        await status_command(update, context)
    elif action == MENU_POSITIONS:
        await positions_command(update, context)
    elif action == MENU_SETTINGS:
        await settings_command(update, context)
    elif action == MENU_EXCHANGE:
        await exchange_command(update, context)
    elif action == MENU_STRATEGY:
        await strategy_command(update, context)
    elif action == MENU_STREAM:
        await stream_command(update, context)
    elif action == MENU_START:
        await start_bot_command(update, context)
    elif action == MENU_PAUSE:
        await pause_bot_command(update, context)
    elif action == MENU_TEST:
        await test_command(update, context)
    elif action == MENU_STOP:
        await update.message.reply_text(
            "❌ <b>Trading Bot has been stopped.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
