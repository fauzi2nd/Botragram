"""
Botragram

Description:
    Telegram bot inline keyboard layouts.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Third Party
# =============================================================================
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# =============================================================================
# Keyboard Helpers
# =============================================================================
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Get main menu inline markup keyboard.

    Returns:
        InlineKeyboardMarkup instance.
    """
    keyboard = [
        [
            InlineKeyboardButton("📊 Status", callback_data="cb_status"),
            InlineKeyboardButton("💼 Positions", callback_data="cb_positions"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="cb_settings"),
            InlineKeyboardButton("🛑 Stop Bot", callback_data="cb_stop"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
