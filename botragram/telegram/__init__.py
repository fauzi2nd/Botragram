"""
Botragram

Description:
    Telegram package initialization.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.telegram.bot import TelegramBot
from botragram.telegram.handlers import register_handlers
from botragram.telegram.keyboards import get_main_menu_keyboard
from botragram.telegram.messages import (
    get_paper_entry_message,
    get_paper_exit_message,
    get_positions_message,
    get_settings_message,
    get_status_message,
    get_trade_completed_message,
    get_welcome_message,
)

__all__ = [
    "TelegramBot",
    "get_main_menu_keyboard",
    "get_paper_entry_message",
    "get_paper_exit_message",
    "get_positions_message",
    "get_settings_message",
    "get_status_message",
    "get_trade_completed_message",
    "get_welcome_message",
    "register_handlers",
]
