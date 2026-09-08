"""
Botragram

Description:
    Telegram bot commands for configuring futures leverage.

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
# Third Party Imports
# =============================================================================
from telegram import Update
from telegram.ext import ContextTypes

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import DEFAULT_PARSE_MODE
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext
from botragram.telegram.keyboards import get_leverage_keyboard
from botragram.telegram.messages import get_leverage_message

__all__ = ["leverage_command", "set_leverage_command"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_MAX_LEVERAGE: Final[int] = 100


def _get_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    value = context.bot_data.get(BOT_CONTEXT_KEY)
    return value if isinstance(value, BotContext) else BotContext()


async def leverage_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display current futures leverage and interactive tuning controls."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    if message is None:
        return

    bot_context = _get_context(context)
    control = bot_context.runtime_control
    is_paused = control.is_paused if control is not None else False

    msg = get_leverage_message(
        current_leverage=bot_context.leverage,
        max_leverage=_MAX_LEVERAGE,
        is_paused=is_paused,
    )
    keyboard = get_leverage_keyboard(
        current_leverage=bot_context.leverage,
        max_leverage=_MAX_LEVERAGE,
    )
    await message.reply_text(
        msg,
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=keyboard,
    )


async def set_leverage_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Durably update futures leverage while the trading runtime is paused."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    if message is None:
        return

    bot_context = _get_context(context)
    control = bot_context.runtime_control
    if control is None:
        await message.reply_text(
            "⚠️ <b>Runtime control tidak tersedia.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    if not control.is_paused:
        _LOGGER.warning("Rejected /setleverage because runtime is not paused")
        await message.reply_text(
            "⚠️ <b>Jeda (pause) bot terlebih dahulu sebelum mengubah leverage!</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    args = context.args or []
    if len(args) != 1:
        await message.reply_text(
            "ℹ️ <b>Format penggunaan:</b> <code>/setleverage &lt;1-100&gt;</code>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    try:
        new_leverage = int(args[0])
        if new_leverage < 1 or new_leverage > _MAX_LEVERAGE:
            raise ValueError(f"Leverage harus bernilai antara 1 dan {_MAX_LEVERAGE}")
    except ValueError as error:
        await message.reply_text(
            f"⚠️ <b>Nilai leverage tidak valid:</b> {error}",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    try:
        control.select_leverage(new_leverage)
    except (RuntimeError, ValueError) as error:
        _LOGGER.warning("Leverage update rejected: %s", error)
        await message.reply_text(
            f"⚠️ <b>Gagal memperbarui leverage:</b> {error}",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    bot_context.leverage = new_leverage
    _LOGGER.info("Leverage updated via Telegram: %dx", new_leverage)
    await message.reply_text(
        f"✅ <b>Leverage berhasil diatur ke {new_leverage}x.</b>\n"
        "Lanjutkan trading (resume) saat siap.",
        parse_mode=DEFAULT_PARSE_MODE,
    )
