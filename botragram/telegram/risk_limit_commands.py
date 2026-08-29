"""Telegram commands for durable autonomous LIVE runtime risk limits."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Final

from telegram import Update
from telegram.ext import ContextTypes

from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext

__all__ = ["risk_limits_command", "set_risk_limits_command"]

_USAGE: Final[str] = "/setrisklimits <max_open_positions> <max_position_size_usdt>"


def _get_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    value = context.bot_data.get(BOT_CONTEXT_KEY)
    return value if isinstance(value, BotContext) else BotContext()


async def risk_limits_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display current durable runtime limits and immutable env ceilings."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    service = _get_context(context).runtime_risk_limit_service
    if message is None:
        return
    if service is None:
        await message.reply_text("Runtime risk limits are unavailable in this mode.")
        return

    limits = service.get_snapshot()
    await message.reply_text(
        "Runtime Risk Limits\n"
        f"Open positions: {limits.max_open_positions} "
        f"(maximum {service.max_open_positions_ceiling})\n"
        f"Position size: {limits.max_position_size_usdt} USDT "
        f"(maximum {service.max_position_size_usdt_ceiling} USDT)\n"
        f"Source: {limits.updated_by}\n"
        f"Updated: {limits.updated_at.isoformat()}"
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
