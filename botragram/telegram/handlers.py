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
    orders_command,
    positions_command,
    settings_command,
    start_command,
    status_command,
    stream_command,
    trading_mode_command,
)
from botragram.telegram.operator_exit_commands import (
    cancel_exit_command,
    close_all_and_switch_command,
    close_all_command,
    close_position_command,
    confirm_exit_command,
    exit_status_command,
)
from botragram.telegram.operator_exit_progress import (
    operator_exit_confirm_callback_with_progress,
)
from botragram.telegram.risk_limit_commands import (
    risk_limits_command,
    set_risk_limits_command,
)
from botragram.telegram.runtime_menu_refresh import (
    menu_message_handler_with_runtime_refresh,
    pause_bot_command_with_menu_refresh,
    start_bot_command_with_menu_refresh,
)
from botragram.telegram.strategy_flatten_switch import (
    strategy_flatten_confirm_callback,
    strategy_flatten_request_callback,
)
from botragram.telegram.strategy_switch import (
    strategy_switch_callback,
    strategy_switch_command,
)


def register_handlers(app: Any) -> None:
    """Register command and callback handlers on Telegram app."""
    app.add_handler(CommandHandler(CMD_START, start_command))
    app.add_handler(CommandHandler(CMD_STATUS, status_command))
    app.add_handler(CommandHandler(CMD_POSITIONS, positions_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("market", market_command))
    app.add_handler(CommandHandler("strategy", strategy_switch_command))
    app.add_handler(CommandHandler("interval", interval_command))
    app.add_handler(CommandHandler("stream", stream_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("pause", pause_bot_command_with_menu_refresh))
    app.add_handler(CommandHandler("resume", start_bot_command_with_menu_refresh))
    app.add_handler(CommandHandler(CMD_SETTINGS, settings_command))
    app.add_handler(CommandHandler("exchange", exchange_command))
    app.add_handler(CommandHandler("mode", trading_mode_command))
    app.add_handler(CommandHandler("risklimits", risk_limits_command))
    app.add_handler(CommandHandler("setrisklimits", set_risk_limits_command))
    app.add_handler(CommandHandler("exitstatus", exit_status_command))
    app.add_handler(CommandHandler("closeposition", close_position_command))
    app.add_handler(CommandHandler("closeall", close_all_command))
    app.add_handler(CommandHandler("closeandswitch", close_all_and_switch_command))
    app.add_handler(CommandHandler("confirmexit", confirm_exit_command))
    app.add_handler(CommandHandler("cancelexit", cancel_exit_command))
    app.add_handler(
        CallbackQueryHandler(
            strategy_flatten_confirm_callback,
            pattern=r"^cb_strategy_exit_confirm_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            strategy_flatten_request_callback,
            pattern=r"^cb_strategy_flatten_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            operator_exit_confirm_callback_with_progress,
            pattern=r"^cb_operator_exit_confirm_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            strategy_switch_callback,
            pattern=r"^cb_strategy($|_)",
        )
    )
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            menu_message_handler_with_runtime_refresh,
        )
    )
