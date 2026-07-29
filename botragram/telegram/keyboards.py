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
            InlineKeyboardButton("🔄 Exchange", callback_data="cb_exchange"),
        ],
        [
            InlineKeyboardButton("🛑 Stop Bot", callback_data="cb_stop"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_exchange_keyboard(active_exchange: str = "BYBIT") -> InlineKeyboardMarkup:
    """Get exchange selection inline keyboard.

    Args:
        active_exchange: Currently active exchange name (uppercase).

    Returns:
        InlineKeyboardMarkup instance.
    """

    def _label(name: str, emoji: str) -> str:
        check = "✅ " if active_exchange.upper() == name else ""
        return f"{check}{emoji} {name}"

    keyboard = [
        [
            InlineKeyboardButton(
                _label("BYBIT", "🟡"),
                callback_data="cb_exchange_bybit",
            ),
            InlineKeyboardButton(
                _label("BINANCE", "🟠"),
                callback_data="cb_exchange_binance",
            ),
        ],
        [
            InlineKeyboardButton(
                _label("OKX", "⚫"),
                callback_data="cb_exchange_okx",
            ),
            InlineKeyboardButton(
                _label("BITGET", "🔵"),
                callback_data="cb_exchange_bitget",
            ),
        ],
        [
            InlineKeyboardButton("◀️ Back", callback_data="cb_back_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
