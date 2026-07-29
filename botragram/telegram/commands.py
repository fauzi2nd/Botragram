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

# =============================================================================
# Standard Library
# =============================================================================
import logging
from decimal import Decimal

# =============================================================================
# Third Party
# =============================================================================
from telegram import Update
from telegram.ext import ContextTypes

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import DEFAULT_PARSE_MODE
from botragram.telegram.keyboards import get_main_menu_keyboard
from botragram.telegram.messages import (
    get_positions_message,
    get_settings_message,
    get_status_message,
    get_welcome_message,
)

logger = logging.getLogger(__name__)


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
        msg = get_status_message(
            is_running=True,
            trade_mode="PAPER",
            symbol="BTCUSDT",
            last_price=Decimal("50000.0"),
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
        msg = get_positions_message([])
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
        msg = get_settings_message(
            exchange_type="BYBIT",
            strategy_name="EMA_CROSS",
            trade_mode="PAPER",
        )
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)
