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
from botragram.telegram.messages import (
    get_positions_message,
    get_settings_message,
    get_status_message,
)

logger = logging.getLogger(__name__)


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

    if data == "cb_status":
        msg = get_status_message(
            is_running=True,
            trade_mode="PAPER",
            symbol="BTCUSDT",
            last_price=Decimal("50000.0"),
        )
        await query.edit_message_text(msg, parse_mode=DEFAULT_PARSE_MODE)
    elif data == "cb_positions":
        msg = get_positions_message([])
        await query.edit_message_text(msg, parse_mode=DEFAULT_PARSE_MODE)
    elif data == "cb_settings":
        msg = get_settings_message(
            exchange_type="BYBIT",
            strategy_name="EMA_CROSS",
            trade_mode="PAPER",
        )
        await query.edit_message_text(msg, parse_mode=DEFAULT_PARSE_MODE)
    elif data == "cb_stop":
        await query.edit_message_text(
            "🛑 <b>Trading Bot has been paused.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
