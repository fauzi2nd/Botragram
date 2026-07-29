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
from botragram.enums.exchange_type import ExchangeType
from botragram.telegram.context import BotContext
from botragram.telegram.keyboards import get_exchange_keyboard, get_main_menu_keyboard
from botragram.telegram.messages import (
    get_exchange_message,
    get_exchange_switched_message,
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

    # ------------------------------------------------------------------
    # Main menu navigation
    # ------------------------------------------------------------------
    if data == "cb_status":
        msg = get_status_message(
            is_running=ctx.is_running,
            trade_mode=ctx.trade_mode,
            symbol=ctx.symbol,
            last_price=ctx.last_price,
        )
        await query.edit_message_text(
            msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=get_main_menu_keyboard()
        )

    elif data == "cb_positions":
        msg = get_positions_message(ctx.positions)
        await query.edit_message_text(
            msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=get_main_menu_keyboard()
        )

    elif data == "cb_settings":
        msg = get_settings_message(
            exchange_type=ctx.exchange_type,
            strategy_name=ctx.strategy_name,
            trade_mode=ctx.trade_mode,
        )
        await query.edit_message_text(
            msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=get_main_menu_keyboard()
        )

    elif data == "cb_stop":
        if ctx.application:
            await ctx.application.engine.stop()
        await query.edit_message_text(
            "🛑 <b>Trading Bot has been paused.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )

    elif data == "cb_back_main":
        msg = get_status_message(
            is_running=ctx.is_running,
            trade_mode=ctx.trade_mode,
            symbol=ctx.symbol,
            last_price=ctx.last_price,
        )
        await query.edit_message_text(
            msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=get_main_menu_keyboard()
        )

    # ------------------------------------------------------------------
    # Exchange selection menu
    # ------------------------------------------------------------------
    elif data == "cb_exchange":
        msg = get_exchange_message(ctx.exchange_type)
        await query.edit_message_text(
            msg,
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_exchange_keyboard(ctx.exchange_type),
        )

    elif data in (
        "cb_exchange_bybit",
        "cb_exchange_binance",
        "cb_exchange_okx",
        "cb_exchange_bitget",
    ):
        exchange_map: dict[str, ExchangeType] = {
            "cb_exchange_bybit": ExchangeType.BYBIT,
            "cb_exchange_binance": ExchangeType.BINANCE,
            "cb_exchange_okx": ExchangeType.OKX,
            "cb_exchange_bitget": ExchangeType.BITGET,
        }
        new_exchange = exchange_map[data]
        new_exchange_name = new_exchange.value.upper()

        if ctx.application:
            try:
                await ctx.application.switch_exchange(new_exchange)
                # Update context exchange name
                context.bot_data[BOT_CONTEXT_KEY] = BotContext(
                    is_running=ctx.is_running,
                    trade_mode=ctx.trade_mode,
                    symbol=ctx.symbol,
                    strategy_name=ctx.strategy_name,
                    exchange_type=new_exchange_name,
                    last_price=ctx.last_price,
                    positions=ctx.positions,
                    application=ctx.application,
                )
                msg = get_exchange_switched_message(new_exchange_name)
                await query.edit_message_text(
                    msg,
                    parse_mode=DEFAULT_PARSE_MODE,
                    reply_markup=get_exchange_keyboard(new_exchange_name),
                )
            except Exception as e:
                logger.exception(f"Exchange switch failed: {e}")
                await query.edit_message_text(
                    f"❌ <b>Gagal ganti exchange:</b> {e}",
                    parse_mode=DEFAULT_PARSE_MODE,
                    reply_markup=get_exchange_keyboard(ctx.exchange_type),
                )
        else:
            await query.edit_message_text(
                f"⚠️ <b>Tidak dapat ganti exchange</b> — application tidak tersedia.",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_main_menu_keyboard(),
            )
