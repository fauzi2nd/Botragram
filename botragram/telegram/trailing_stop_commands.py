"""
Botragram

Description:
    Telegram bot commands for configuring Trailing Stop.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

import logging

# =============================================================================
# Standard Library Imports
# =============================================================================
from decimal import Decimal, InvalidOperation
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
from botragram.telegram.keyboards import get_trailing_stop_keyboard
from botragram.telegram.messages import get_trailing_stop_message

__all__ = ["set_trailing_stop_command", "trailing_stop_command"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


def _get_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    value = context.bot_data.get(BOT_CONTEXT_KEY)
    return value if isinstance(value, BotContext) else BotContext()


async def trailing_stop_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display current Trailing Stop settings and interactive controls."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    if message is None:
        return

    bot_context = _get_context(context)
    control = bot_context.runtime_control
    is_paused = control.is_paused if control is not None else False

    enabled = (
        control.trailing_stop_enabled
        if control is not None
        else bot_context.trailing_stop_enabled
    )
    trigger = (
        control.trailing_stop_trigger_pct
        if control is not None
        else bot_context.trailing_stop_trigger_pct
    )
    distance = (
        control.trailing_stop_distance_pct
        if control is not None
        else bot_context.trailing_stop_distance_pct
    )

    msg = get_trailing_stop_message(
        enabled=enabled,
        trigger_pct=trigger,
        distance_pct=distance,
        is_paused=is_paused,
    )
    keyboard = get_trailing_stop_keyboard(
        enabled=enabled,
        trigger_pct=trigger,
        distance_pct=distance,
    )
    await message.reply_text(
        msg,
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=keyboard,
    )


async def set_trailing_stop_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Set Trailing Stop via CLI command: /settrail <on|off> [trigger_%] [dist_%]."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    if message is None:
        return

    bot_context = _get_context(context)
    control = bot_context.runtime_control
    is_paused = control.is_paused if control is not None else False

    if not is_paused:
        await message.reply_text(
            "⚠️ <b>Jeda trading (/pause) terlebih dahulu sebelum mengubah "
            "konfigurasi Trailing Stop!</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    args = context.args or []
    if not args:
        await message.reply_text(
            "ℹ️ <b>Format penggunaan:</b>\n"
            "<code>/settrail &lt;on|off&gt; [trigger_%] [dist_%]</code>\n\n"
            "Contoh:\n"
            "• <code>/settrail on 1.5 0.8</code>\n"
            "• <code>/settrail off</code>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    mode_str = args[0].strip().lower()
    if mode_str in {"on", "true", "1", "enable", "aktif"}:
        new_enabled = True
    elif mode_str in {"off", "false", "0", "disable", "nonaktif"}:
        new_enabled = False
    else:
        await message.reply_text(
            "⚠️ Status harus bernilai 'on' atau 'off'.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    current_trig = (
        control.trailing_stop_trigger_pct
        if control is not None
        else bot_context.trailing_stop_trigger_pct
    )
    current_dist = (
        control.trailing_stop_distance_pct
        if control is not None
        else bot_context.trailing_stop_distance_pct
    )

    new_trig = current_trig
    new_dist = current_dist

    if len(args) >= 2:
        try:
            val_trig = Decimal(args[1]) / Decimal("100")
            if not (Decimal("0") < val_trig < Decimal("1")):
                raise ValueError
            new_trig = val_trig
        except ValueError, InvalidOperation:
            await message.reply_text(
                "⚠️ Persentase Trigger tidak valid (contoh: 1.5 untuk 1.5%).",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return

    if len(args) >= 3:
        try:
            val_dist = Decimal(args[2]) / Decimal("100")
            if not (Decimal("0") < val_dist < Decimal("1")):
                raise ValueError
            new_dist = val_dist
        except ValueError, InvalidOperation:
            await message.reply_text(
                "⚠️ Persentase Distance tidak valid (contoh: 0.8 untuk 0.8%).",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return

    if new_dist >= new_trig:
        await message.reply_text(
            "⚠️ Distance harus lebih kecil dari Trigger.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    if control is not None:
        try:
            control.select_trailing_stop(
                enabled=new_enabled,
                trigger_pct=new_trig,
                distance_pct=new_dist,
            )
        except Exception as error:
            await message.reply_text(
                f"⚠️ Gagal menyimpan pengaturan: {error}",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return

    bot_context.trailing_stop_enabled = new_enabled
    bot_context.trailing_stop_trigger_pct = new_trig
    bot_context.trailing_stop_distance_pct = new_dist

    status_str = "🟢 <b>ACTIVE</b>" if new_enabled else "🔴 <b>DISABLED</b>"
    await message.reply_text(
        f"✅ <b>Trailing Stop berhasil diperbarui:</b>\n"
        f"• Status: {status_str}\n"
        f"• Trigger: <b>+{new_trig * Decimal('100'):.2f}%</b>\n"
        f"• Distance: <b>{new_dist * Decimal('100'):.2f}%</b>",
        parse_mode=DEFAULT_PARSE_MODE,
    )
