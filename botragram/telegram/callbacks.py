"""
Botragram

Description:
    Telegram callback query handlers.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
import logging
from typing import Final

# =============================================================================
# Third-Party Imports
# =============================================================================
from telegram import Update
from telegram.ext import ContextTypes

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import DEFAULT_PARSE_MODE
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext
from botragram.telegram.keyboards import get_exchange_keyboard
from botragram.telegram.messages import (
    get_exchange_message,
    get_positions_message,
    get_settings_message,
    get_status_message,
)

__all__ = [
    "handle_callback_query",
]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_EXCHANGE_CALLBACKS: Final[frozenset[str]] = frozenset(
    {
        "cb_exchange_bybit",
        "cb_exchange_binance",
        "cb_exchange_okx",
        "cb_exchange_bitget",
    }
)


# =============================================================================
# Helpers
# =============================================================================
def _get_context(
    context: ContextTypes.DEFAULT_TYPE,
) -> BotContext:
    """Return the stored Botragram context or safe defaults."""
    bot_context = context.bot_data.get(BOT_CONTEXT_KEY)

    if isinstance(bot_context, BotContext):
        return bot_context

    return BotContext()


# =============================================================================
# Callback Handler
# =============================================================================
async def handle_callback_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle navigation callbacks without mutating trading configuration."""
    query = update.callback_query

    if query is None or not is_authorized_update(update=update, context=context):
        return

    await query.answer()
    data = query.data or ""
    bot_context = _get_context(context)

    if data in {"cb_status", "cb_back_main"}:
        last_price = bot_context.last_price
        available_balance = None
        open_position_count = None
        provider = bot_context.query_provider

        if provider is not None:
            try:
                positions = await provider.get_positions()
                last_price = await provider.get_last_price()
                available_balance = await provider.get_available_balance()
                open_position_count = len(positions)
            except Exception:
                _LOGGER.exception("Telegram callback status query failed")

        message = get_status_message(
            is_running=bot_context.is_running,
            trade_mode=bot_context.trade_mode,
            symbol=bot_context.symbol,
            last_price=last_price,
            available_balance=available_balance,
            open_position_count=open_position_count,
            is_paused=(
                bot_context.runtime_control.is_paused
                if bot_context.runtime_control is not None
                else False
            ),
        )
        await query.edit_message_text(message, parse_mode=DEFAULT_PARSE_MODE)
    elif data == "cb_positions":
        positions = bot_context.positions

        if bot_context.query_provider is not None:
            try:
                positions = tuple(await bot_context.query_provider.get_positions())
            except Exception:
                _LOGGER.exception("Telegram callback positions query failed")

        await query.edit_message_text(
            get_positions_message(positions),
            parse_mode=DEFAULT_PARSE_MODE,
        )
    elif data == "cb_settings":
        await query.edit_message_text(
            get_settings_message(
                exchange_type=bot_context.exchange_type,
                strategy_name=bot_context.strategy_name,
                trade_mode=bot_context.trade_mode,
            ),
            parse_mode=DEFAULT_PARSE_MODE,
        )
    elif data == "cb_stop":
        await query.edit_message_text(
            "ℹ️ <b>Kontrol runtime belum tersedia melalui Telegram.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
    elif data == "cb_exchange":
        await query.edit_message_text(
            get_exchange_message(bot_context.exchange_type),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_exchange_keyboard(bot_context.exchange_type),
        )
    elif data in _EXCHANGE_CALLBACKS:
        await query.edit_message_text(
            "⚠️ <b>Perubahan exchange saat runtime belum didukung.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_exchange_keyboard(bot_context.exchange_type),
        )
