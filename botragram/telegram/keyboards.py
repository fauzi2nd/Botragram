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
# Standard Library Imports
# =============================================================================
from collections.abc import Sequence
from typing import Final
from uuid import UUID

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
    MENU_MARKET_OVERVIEW,
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
from botragram.enums import MarketType

__all__ = [
    "get_activity_menu_keyboard",
    "get_configuration_menu_keyboard",
    "get_dashboard_menu_keyboard",
    "get_exchange_keyboard",
    "get_interval_keyboard",
    "get_main_menu_keyboard",
    "get_market_keyboard",
    "get_market_search_keyboard",
    "get_strategy_keyboard",
    "get_stream_keyboard",
    "get_execution_authorization_keyboard",
    "get_trading_menu_keyboard",
]


_MARKET_PAGE_SIZE: Final[int] = 10


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
            [MENU_MARKET_OVERVIEW, MENU_BALANCE],
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


def get_exchange_keyboard(
    active_exchange: str = "BINANCE",
    market_type: MarketType = MarketType.SPOT,
    *,
    exchange_confirmed: bool = False,
    market_type_confirmed: bool = False,
) -> InlineKeyboardMarkup:
    """Get exchange selection inline keyboard.

    Args:
        active_exchange: Currently active exchange name (uppercase).
        market_type: Currently active exchange product family.
        exchange_confirmed: Whether Telegram confirmed the exchange.
        market_type_confirmed: Whether Telegram confirmed the product family.

    Returns:
        InlineKeyboardMarkup instance.
    """

    def _label(name: str, emoji: str) -> str:
        check = "✅ " if exchange_confirmed and active_exchange.upper() == name else ""
        return f"{check}{emoji} {name}"

    normalized = active_exchange.strip().upper()
    emoji = "🟠" if normalized == "BINANCE" else "🟡"
    spot_check = (
        "✅ " if market_type_confirmed and market_type is MarketType.SPOT else ""
    )
    futures_check = (
        "✅ " if market_type_confirmed and market_type is MarketType.FUTURES else ""
    )
    keyboard = [
        [
            InlineKeyboardButton(
                _label(normalized, emoji),
                callback_data=f"cb_exchange_{normalized.lower()}",
            )
        ],
        [
            InlineKeyboardButton(
                f"{spot_check}Spot",
                callback_data="cb_product_spot",
            ),
            InlineKeyboardButton(
                f"{futures_check}Futures",
                callback_data="cb_product_futures",
            ),
        ],
        [
            InlineKeyboardButton("◀️ Back", callback_data="cb_back_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_interval_keyboard(
    active_interval: str,
    *,
    confirmed: bool = False,
) -> InlineKeyboardMarkup:
    """Return the supported candle-interval selection keyboard."""
    buttons = [
        InlineKeyboardButton(
            f"{'✅ ' if confirmed and value == active_interval else ''}{value}",
            callback_data=f"cb_interval_{value}",
        )
        for value in TELEGRAM_INTERVALS
    ]
    return InlineKeyboardMarkup(
        [buttons[index : index + 4] for index in range(0, len(buttons), 4)]
        + [[InlineKeyboardButton("◀️ Back", callback_data="cb_back_main")]]
    )


def get_market_keyboard(
    active_symbol: str,
    symbols: Sequence[str] = TELEGRAM_MARKET_SYMBOLS,
    page: int | None = None,
    *,
    confirmed: bool = False,
) -> InlineKeyboardMarkup:
    """Return one page of exchange-supported market symbols."""
    normalized_symbols = tuple(sorted({symbol.strip().upper() for symbol in symbols}))

    if not normalized_symbols:
        raise ValueError("Market keyboard requires at least one symbol")

    normalized_active = active_symbol.strip().upper()
    maximum_page = (len(normalized_symbols) - 1) // _MARKET_PAGE_SIZE

    if page is None:
        try:
            active_index = normalized_symbols.index(normalized_active)
        except ValueError:
            active_index = 0

        selected_page = active_index // _MARKET_PAGE_SIZE
    else:
        selected_page = min(max(page, 0), maximum_page)

    start = selected_page * _MARKET_PAGE_SIZE
    page_symbols = normalized_symbols[start : start + _MARKET_PAGE_SIZE]
    buttons = [
        InlineKeyboardButton(
            f"{'✅ ' if confirmed and symbol == normalized_active else ''}{symbol}",
            callback_data=f"cb_market_{symbol.lower()}",
        )
        for symbol in page_symbols
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    navigation: list[InlineKeyboardButton] = []

    if selected_page > 0:
        navigation.append(
            InlineKeyboardButton(
                "⬅️ Prev",
                callback_data=f"cb_market_page_{selected_page - 1}",
            )
        )

    navigation.append(
        InlineKeyboardButton(
            f"{selected_page + 1}/{maximum_page + 1}",
            callback_data="cb_market_noop",
        )
    )

    if selected_page < maximum_page:
        navigation.append(
            InlineKeyboardButton(
                "Next ➡️",
                callback_data=f"cb_market_page_{selected_page + 1}",
            )
        )

    rows.append(navigation)
    rows.append([InlineKeyboardButton("🔎 Search", callback_data="cb_market_search")])
    rows.append([InlineKeyboardButton("◀️ Back", callback_data="cb_back_main")])
    return InlineKeyboardMarkup(rows)


def get_market_search_keyboard(
    active_symbol: str,
    symbols: Sequence[str],
    *,
    confirmed: bool = False,
) -> InlineKeyboardMarkup:
    """Return compact selectable exchange-symbol search results."""
    normalized_active = active_symbol.strip().upper()
    normalized_symbols = tuple(sorted({symbol.strip().upper() for symbol in symbols}))
    buttons = [
        InlineKeyboardButton(
            f"{'✅ ' if confirmed and symbol == normalized_active else ''}{symbol}",
            callback_data=f"cb_market_{symbol.lower()}",
        )
        for symbol in normalized_symbols
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "🔎 Search Again",
                    callback_data="cb_market_search",
                )
            ],
            [InlineKeyboardButton("◀️ Back", callback_data="cb_back_main")],
        ]
    )
    return InlineKeyboardMarkup(rows)


def get_strategy_keyboard(
    active_strategy: str,
    *,
    confirmed: bool = False,
) -> InlineKeyboardMarkup:
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
            f"{'✅ ' if confirmed and value == normalized_active else ''}{label}",
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


def get_execution_authorization_keyboard(
    authorization_id: str,
) -> InlineKeyboardMarkup:
    """Return PAPER approval controls for one opaque authorization identifier."""
    normalized_identifier = _normalize_authorization_identifier(authorization_id)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Approve PAPER",
                    callback_data=f"cb_opportunity_approve_{normalized_identifier}",
                ),
                InlineKeyboardButton(
                    "Reject",
                    callback_data=f"cb_opportunity_reject_{normalized_identifier}",
                ),
            ]
        ]
    )


def _normalize_authorization_identifier(authorization_id: str) -> str:
    """Validate the fixed-width opaque identifier used in callback data."""
    normalized_identifier = authorization_id.strip().lower()

    try:
        parsed_identifier = UUID(hex=normalized_identifier)
    except ValueError as error:
        raise ValueError("Execution authorization identifier must be a UUID") from error

    if parsed_identifier.hex != normalized_identifier:
        raise ValueError("Execution authorization identifier must be canonical")

    return normalized_identifier
