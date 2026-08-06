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
from typing import Final

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
    MENU_BALANCE,
    MENU_EXCHANGE,
    MENU_HISTORY,
    MENU_MARKET,
    MENU_ORDERS,
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
from botragram.models import Order, Trade
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext
from botragram.telegram.keyboards import get_exchange_keyboard, get_main_menu_keyboard
from botragram.telegram.messages import (
    get_balance_message,
    get_exchange_message,
    get_history_message,
    get_market_message,
    get_orders_message,
    get_positions_message,
    get_resume_message,
    get_runtime_pause_message,
    get_settings_message,
    get_status_message,
    get_strategy_message,
    get_stream_message,
    get_test_message,
    get_welcome_message,
)

logger: Final[logging.Logger] = logging.getLogger(__name__)
_HISTORY_LIMIT: Final[int] = 10
_ORDER_LIMIT: Final[int] = 10
_DATA_UNAVAILABLE_MESSAGE: Final[str] = (
    "⚠️ <b>Data sementara tidak tersedia.</b> Silakan coba lagi."
)


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


async def _reply_data_unavailable(update: Update) -> None:
    """Return a truthful transient query failure response."""
    if update.message is not None:
        await update.message.reply_text(
            _DATA_UNAVAILABLE_MESSAGE,
            parse_mode=DEFAULT_PARSE_MODE,
        )


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
        if not is_authorized_update(update=update, context=context):
            return

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
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        last_price = ctx.last_price
        available_balance: Decimal | None = None
        open_position_count: int | None = None
        provider = ctx.query_provider

        if provider is not None:
            try:
                positions = await provider.get_positions()
                last_price = await provider.get_last_price()
                available_balance = await provider.get_available_balance()
                open_position_count = len(positions)
            except Exception:
                logger.exception("Telegram status query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_status_message(
            is_running=ctx.is_running,
            trade_mode=ctx.trade_mode,
            symbol=ctx.symbol,
            last_price=last_price,
            available_balance=available_balance,
            open_position_count=open_position_count,
            is_paused=(
                ctx.runtime_control.is_paused
                if ctx.runtime_control is not None
                else False
            ),
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
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        positions = ctx.positions

        if ctx.query_provider is not None:
            try:
                positions = tuple(await ctx.query_provider.get_positions())
            except Exception:
                logger.exception("Telegram positions query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_positions_message(positions)
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
        if not is_authorized_update(update=update, context=context):
            return

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
        if not is_authorized_update(update=update, context=context):
            return

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
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        last_price = ctx.last_price

        if ctx.query_provider is not None:
            try:
                last_price = await ctx.query_provider.get_last_price()
            except Exception:
                logger.exception("Telegram market query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_market_message(ctx.symbol, last_price)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def orders_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        orders: tuple[Order, ...] = ()

        if ctx.query_provider is not None:
            try:
                orders = tuple(
                    await ctx.query_provider.get_latest_orders(limit=_ORDER_LIMIT)
                )
            except Exception:
                logger.exception("Telegram orders query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_orders_message(orders)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        balance = Decimal("0")

        if ctx.query_provider is not None:
            try:
                balance = await ctx.query_provider.get_available_balance()
            except Exception:
                logger.exception("Telegram balance query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_balance_message(balance)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def history_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        trades: tuple[Trade, ...] = ()

        if ctx.query_provider is not None:
            try:
                trades = tuple(
                    await ctx.query_provider.get_latest_trades(limit=_HISTORY_LIMIT)
                )
            except Exception:
                logger.exception("Telegram history query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_history_message(trades)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def strategy_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

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
        if not is_authorized_update(update=update, context=context):
            return

        msg = get_stream_message()
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def start_bot_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        control = ctx.runtime_control

        if control is None:
            await _reply_data_unavailable(update)
            return

        msg = get_resume_message(changed=control.resume())
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def pause_bot_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        control = ctx.runtime_control

        if control is None:
            await _reply_data_unavailable(update)
            return

        msg = get_runtime_pause_message(changed=control.pause())
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def test_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

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

    if not is_authorized_update(update=update, context=context):
        return

    action = update.message.text
    if action == MENU_STATUS:
        await status_command(update, context)
    elif action == MENU_POSITIONS:
        await positions_command(update, context)
    elif action == MENU_MARKET:
        await market_command(update, context)
    elif action == MENU_ORDERS:
        await orders_command(update, context)
    elif action == MENU_BALANCE:
        await balance_command(update, context)
    elif action == MENU_HISTORY:
        await history_command(update, context)
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
