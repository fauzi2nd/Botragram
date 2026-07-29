"""
Botragram

Description:
    Telegram bot callback query handlers.

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
from botragram.telegram.keyboards import get_main_menu_keyboard
from botragram.telegram.messages import (
    get_positions_message,
    get_settings_message,
    get_status_message,
)

logger = logging.getLogger(__name__)

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
# Callback Handlers
# =============================================================================
async def handle_callback_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle inline button callback queries.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    query = update.callback_query
    if query is None:
        return

    await query.answer()
    data = query.data or ""
    ctx = _get_context(context)

    if data == "cb_status":
        msg = get_status_message(
            is_running=ctx.is_running,
            trade_mode=ctx.trade_mode,
            symbol=ctx.symbol,
            last_price=ctx.last_price,
        )
        kb = get_main_menu_keyboard()
        await query.edit_message_text(msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=kb)

    elif data == "cb_positions":
        msg = get_positions_message(ctx.positions)
        kb = get_main_menu_keyboard()
        await query.edit_message_text(msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=kb)

    elif data == "cb_settings":
        msg = get_settings_message(
            exchange_type=ctx.exchange_type,
            strategy_name=ctx.strategy_name,
            trade_mode=ctx.trade_mode,
        )
        kb = get_main_menu_keyboard()
        await query.edit_message_text(msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=kb)

    elif data == "cb_stop":
        context.bot_data[BOT_CONTEXT_KEY] = BotContext(
            is_running=False,
            trade_mode=ctx.trade_mode,
            symbol=ctx.symbol,
            strategy_name=ctx.strategy_name,
            exchange_type=ctx.exchange_type,
            last_price=ctx.last_price,
            positions=ctx.positions,
        )
        await query.edit_message_text(
            "🛑 <b>Trading Bot has been paused.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
