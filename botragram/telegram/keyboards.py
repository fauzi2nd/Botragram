"""
Botragram

Description:
    Telegram bot reply and inline keyboard layouts.

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
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import (
    MENU_BALANCE,
    MENU_EXCHANGE,
    MENU_HISTORY,
    MENU_MARKET,
    MENU_ORDERS,
    MENU_POSITIONS,
    MENU_SETTINGS,
    MENU_START,
    MENU_STOP,
    MENU_STREAM,
    MENU_STATUS,
    MENU_STRATEGY,
    MENU_PAUSE,
    MENU_TEST,
)


# =============================================================================
# Keyboard Helpers
# =============================================================================
def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Get the persistent main menu shown below Telegram's input field.

    Returns:
        ReplyKeyboardMarkup instance.
    """
    keyboard = [
        [MENU_STATUS, MENU_POSITIONS],
        [MENU_MARKET, MENU_ORDERS],
        [MENU_BALANCE, MENU_HISTORY],
        [MENU_SETTINGS, MENU_EXCHANGE],
        [MENU_STRATEGY, MENU_STREAM],
        [MENU_START, MENU_PAUSE],
        [MENU_TEST, MENU_STOP],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


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
