"""Telegram commands for durable autonomous LIVE runtime risk limits."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Final

from telegram import Update
from telegram.ext import ContextTypes

from botragram.constants.telegram import DEFAULT_PARSE_MODE
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext
from botragram.telegram.keyboards import get_risk_limits_keyboard
from botragram.telegram.messages import get_risk_limits_message

__all__ = ["risk_limits_command", "set_risk_limits_command"]

_USAGE: Final[str] = "/setrisklimits <max_open_positions> <max_position_size_usdt>"


def _get_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    value = context.bot_data.get(BOT_CONTEXT_KEY)
    return value if isinstance(value, BotContext) else BotContext()


async def risk_limits_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display current durable runtime limits and interactive tuning controls."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    bot_context = _get_context(context)
    service = bot_context.runtime_risk_limit_service
    control = bot_context.runtime_control
    if message is None:
        return
    if service is None:
        await message.reply_text(
            "ℹ️ <b>Runtime risk limits tidak tersedia pada mode ini.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    limits = service.get_snapshot()
    is_paused = control.is_paused if control is not None else False
    msg = get_risk_limits_message(
        limits=limits,
        max_open_positions_ceiling=service.max_open_positions_ceiling,
        max_position_size_usdt_ceiling=service.max_position_size_usdt_ceiling,
        is_paused=is_paused,
    )
    keyboard = get_risk_limits_keyboard(
        current_positions=limits.max_open_positions,
        current_size_usdt=limits.max_position_size_usdt,
        max_open_positions_ceiling=service.max_open_positions_ceiling,
        max_position_size_usdt_ceiling=service.max_position_size_usdt_ceiling,
    )
    await message.reply_text(
        msg,
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=keyboard,
    )


async def set_risk_limits_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Durably replace runtime limits while the trading runtime is paused."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    bot_context = _get_context(context)
    service = bot_context.runtime_risk_limit_service
    control = bot_context.runtime_control
    if message is None:
        return
    if service is None or control is None:
        await message.reply_text("Runtime risk limits are unavailable in this mode.")
        return
    if not control.is_paused:
        await message.reply_text("Pause trading before changing runtime risk limits.")
        return
    args = context.args or []
    if len(args) != 2:
        await message.reply_text(
            "Usage: /setrisklimits <open positions> <position size USDT>"
        )
        return

    try:
        max_open_positions = int(args[0])
        max_position_size_usdt = Decimal(args[1])
    except ValueError, InvalidOperation:
        await message.reply_text(
            "Invalid values. Usage: /setrisklimits "
            "<open positions> <position size USDT>"
        )
        return

    user = update.effective_user
    chat = update.effective_chat
    actor_id = user.id if user is not None else (chat.id if chat is not None else 0)
    try:
        limits = await service.update(
            max_open_positions=max_open_positions,
            max_position_size_usdt=max_position_size_usdt,
            updated_by=f"telegram:{actor_id}",
        )
    except (RuntimeError, ValueError) as error:
        await message.reply_text(f"Runtime risk limits rejected: {error}")
        return

    await message.reply_text(
        "Runtime risk limits updated.\n"
        f"Open positions: {limits.max_open_positions}\n"
        f"Position size: {limits.max_position_size_usdt} USDT\n"
        "Resume trading when ready."
    )
