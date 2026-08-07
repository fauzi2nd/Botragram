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
    MENU_ACTIVITY,
    MENU_BALANCE,
    MENU_CONFIGURATION,
    MENU_DASHBOARD,
    MENU_EXCHANGE,
    MENU_HISTORY,
    MENU_HOME,
    MENU_INTERVAL,
    MENU_MARKET,
    MENU_ORDERS,
    MENU_PAUSE,
    MENU_POSITIONS,
    MENU_SETTINGS,
    MENU_START,
    MENU_STATUS,
    MENU_STRATEGY,
    MENU_STREAM,
    MENU_TEST,
    MENU_TRADING,
    TELEGRAM_INTERVALS,
    TELEGRAM_MARKET_SYMBOLS,
)

__all__ = [
    "get_activity_menu_keyboard",
    "get_configuration_menu_keyboard",
    "get_dashboard_menu_keyboard",
    "get_exchange_keyboard",
    "get_interval_keyboard",
    "get_main_menu_keyboard",
    "get_market_keyboard",
    "get_strategy_keyboard",
    "get_stream_keyboard",
    "get_trading_menu_keyboard",
]


# =============================================================================
# Keyboard Helpers
# =============================================================================
def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Get the persistent main menu shown below Telegram's input field.

    Returns:
        ReplyKeyboardMarkup instance.
    """
    return _get_reply_keyboard(
        [[MENU_DASHBOARD, MENU_TRADING], [MENU_CONFIGURATION, MENU_ACTIVITY]]
    )


def get_dashboard_menu_keyboard() -> ReplyKeyboardMarkup:
    """Return the compact monitoring submenu."""
    return _get_reply_keyboard(
        [
            [MENU_STATUS, MENU_POSITIONS],
            [MENU_MARKET, MENU_BALANCE],
            [MENU_HOME],
        ]
    )


def get_trading_menu_keyboard() -> ReplyKeyboardMarkup:
    """Return the compact runtime-control submenu."""
    return _get_reply_keyboard(
        [
            [MENU_START, MENU_PAUSE],
            [MENU_STREAM],
            [MENU_HOME],
        ]
    )


def get_configuration_menu_keyboard() -> ReplyKeyboardMarkup:
    """Return the runtime-configuration submenu."""
    return _get_reply_keyboard(
        [
            [MENU_EXCHANGE, MENU_MARKET],
            [MENU_STRATEGY, MENU_INTERVAL],
            [MENU_SETTINGS],
            [MENU_HOME],
        ]
    )


def get_activity_menu_keyboard() -> ReplyKeyboardMarkup:
    """Return order, history, and diagnostics navigation."""
    return _get_reply_keyboard(
        [
            [MENU_ORDERS, MENU_HISTORY],
            [MENU_TEST],
            [MENU_HOME],
        ]
    )


def _get_reply_keyboard(keyboard: list[list[str]]) -> ReplyKeyboardMarkup:
    """Build one persistent, compact reply keyboard."""
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


def get_exchange_keyboard(active_exchange: str = "BINANCE") -> InlineKeyboardMarkup:
    """Get exchange selection inline keyboard.

    Args:
        active_exchange: Currently active exchange name (uppercase).

    Returns:
        InlineKeyboardMarkup instance.
    """

    def _label(name: str, emoji: str) -> str:
        check = "✅ " if active_exchange.upper() == name else ""
        return f"{check}{emoji} {name}"

    normalized = active_exchange.strip().upper()
    emoji = "🟠" if normalized == "BINANCE" else "🟡"
    keyboard = [
        [
            InlineKeyboardButton(
                _label(normalized, emoji),
                callback_data=f"cb_exchange_{normalized.lower()}",
            )
        ],
        [
            InlineKeyboardButton("◀️ Back", callback_data="cb_back_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_interval_keyboard(active_interval: str) -> InlineKeyboardMarkup:
    """Return the supported candle-interval selection keyboard."""
    buttons = [
        InlineKeyboardButton(
            f"{'✅ ' if value == active_interval else ''}{value}",
            callback_data=f"cb_interval_{value}",
        )
        for value in TELEGRAM_INTERVALS
    ]
    return InlineKeyboardMarkup(
        [buttons[index : index + 4] for index in range(0, len(buttons), 4)]
        + [[InlineKeyboardButton("◀️ Back", callback_data="cb_back_main")]]
    )


def get_market_keyboard(active_symbol: str) -> InlineKeyboardMarkup:
    """Return the supported quote-market selection keyboard."""
    buttons = [
        InlineKeyboardButton(
            f"{'✅ ' if symbol == active_symbol.upper() else ''}{symbol}",
            callback_data=f"cb_market_{symbol.lower()}",
        )
        for symbol in TELEGRAM_MARKET_SYMBOLS
    ]
    return InlineKeyboardMarkup(
        [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
        + [[InlineKeyboardButton("◀️ Back", callback_data="cb_back_main")]]
    )


def get_strategy_keyboard(active_strategy: str) -> InlineKeyboardMarkup:
    """Return the implemented strategy selection keyboard."""
    strategies = (
        ("EMA Cross", "ema_cross"),
        ("EMA + RSI", "ema_rsi"),
        ("EMA Scalping", "ema_scalping"),
        ("MACD Swing", "macd_swing"),
        ("Supertrend", "supertrend"),
        ("Bollinger Breakout", "bollinger_breakout"),
    )
    normalized_active = active_strategy.lower()
    buttons = [
        InlineKeyboardButton(
            f"{'✅ ' if value == normalized_active else ''}{label}",
            callback_data=f"cb_strategy_{value}",
        )
        for label, value in strategies
    ]
    return InlineKeyboardMarkup(
        [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
        + [[InlineKeyboardButton("◀️ Back", callback_data="cb_back_main")]]
    )


def get_stream_keyboard() -> InlineKeyboardMarkup:
    """Return controls for the real background ticker subscription."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("▶️ Start", callback_data="cb_stream_start"),
                InlineKeyboardButton("⏹️ Stop", callback_data="cb_stream_stop"),
            ],
            [InlineKeyboardButton("🔄 Refresh", callback_data="cb_stream_refresh")],
            [InlineKeyboardButton("◀️ Back", callback_data="cb_back_main")],
        ]
    )
