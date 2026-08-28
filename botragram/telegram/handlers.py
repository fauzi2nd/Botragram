"""
Botragram

Description:
    Telegram bot handler registration helper.

Python:
    3.14+
"""

from __future__ import annotations

from typing import Any

from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

from botragram.constants.telegram import (
    CMD_POSITIONS,
    CMD_SETTINGS,
    CMD_START,
    CMD_STATUS,
)
from botragram.telegram.callbacks import handle_callback_query
from botragram.telegram.commands import (
    balance_command,
    exchange_command,
    history_command,
    interval_command,
    market_command,
    menu_message_handler,
    orders_command,
    pause_bot_command,
    positions_command,
    settings_command,
    start_bot_command,
    start_command,
    status_command,
    strategy_command,
    stream_command,
    trading_mode_command,
)
from botragram.telegram.risk_limit_commands import (
    risk_limits_command,
    set_risk_limits_command,
)


def register_handlers(app: Any) -> None:
    """Register command and callback handlers on Telegram app."""
    app.add_handler(CommandHandler(CMD_START, start_command))
    app.add_handler(CommandHandler(CMD_STATUS, status_command))
    app.add_handler(CommandHandler(CMD_POSITIONS, positions_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("market", market_command))
    app.add_handler(CommandHandler("strategy", strategy_command))
    app.add_handler(CommandHandler("interval", interval_command))
    app.add_handler(CommandHandler("stream", stream_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("pause", pause_bot_command))
    app.add_handler(CommandHandler("resume", start_bot_command))
    app.add_handler(CommandHandler(CMD_SETTINGS, settings_command))
    app.add_handler(CommandHandler("exchange", exchange_command))
    app.add_handler(CommandHandler("mode", trading_mode_command))
    app.add_handler(CommandHandler("risklimits", risk_limits_command))
    app.add_handler(CommandHandler("setrisklimits", set_risk_limits_command))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            menu_message_handler,
        )
    )
