"""
Botragram

Description:
    Telegram bot reply and inline keyboard layouts.

Python:
    3.14+
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

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
    MENU_RESUME,
    MENU_RISK_LIMITS,
    MENU_SETTINGS,
    MENU_START,
    MENU_STATUS,
    MENU_STRATEGY,
    MENU_STREAM,
    MENU_TEST,
    MENU_TRADING,
    MENU_TRADING_MODE,
    TELEGRAM_INTERVALS,
    TELEGRAM_MARKET_SYMBOLS,
)
from botragram.enums import ExecutionPolicy, MarketType
from botragram.models import OperatorExitConfirmation, Position

__all__ = [
    "get_activity_menu_keyboard",
    "get_configuration_menu_keyboard",
    "get_dashboard_menu_keyboard",
    "get_exchange_keyboard",
    "get_execution_authorization_keyboard",
    "get_execution_policy_confirmation_keyboard",
    "get_execution_policy_keyboard",
    "get_interval_keyboard",
    "get_main_menu_keyboard",
    "get_market_keyboard",
    "get_market_search_keyboard",
    "get_operator_exit_confirmation_keyboard",
    "get_operator_exit_positions_keyboard",
    "get_operator_flatten_switch_keyboard",
    "get_risk_limits_keyboard",
    "get_status_dashboard_keyboard",
    "get_strategy_keyboard",
    "get_stream_keyboard",
    "get_trading_menu_keyboard",
]

_MARKET_PAGE_SIZE: Final[int] = 10


def get_status_dashboard_keyboard(
    *,
    is_paused: bool = False,
    has_positions: bool = False,
    execution_policy: ExecutionPolicy = ExecutionPolicy.SINGLE_SYMBOL,
) -> InlineKeyboardMarkup:
    """Return interactive quick-action controls synchronized with persistent menu."""
    row1 = [
        InlineKeyboardButton("🔄 Refresh", callback_data="cb_status_refresh"),
        InlineKeyboardButton(MENU_POSITIONS, callback_data="cb_positions"),
    ]
    if has_positions:
        row1.append(
            InlineKeyboardButton(
                "⚠️ Close All",
                callback_data="cb_operator_exit_close_all",
            )
        )

    pause_label = MENU_RESUME if is_paused else MENU_PAUSE
    pause_cb = "cb_runtime_resume" if is_paused else "cb_runtime_pause"

    row2 = [
        InlineKeyboardButton(pause_label, callback_data=pause_cb),
        InlineKeyboardButton(MENU_TRADING_MODE, callback_data="cb_policy_menu"),
    ]

    if execution_policy is ExecutionPolicy.AUTONOMOUS_LIVE:
        row3 = [
            InlineKeyboardButton(MENU_STRATEGY, callback_data="cb_strategy"),
            InlineKeyboardButton(MENU_RISK_LIMITS, callback_data="cb_risk_limits"),
        ]
    else:
        row3 = [
            InlineKeyboardButton(MENU_STRATEGY, callback_data="cb_strategy"),
            InlineKeyboardButton(MENU_INTERVAL, callback_data="cb_interval"),
        ]

    row4 = [
        InlineKeyboardButton(MENU_HISTORY, callback_data="cb_history"),
        InlineKeyboardButton(MENU_ORDERS, callback_data="cb_orders"),
    ]
    return InlineKeyboardMarkup([row1, row2, row3, row4])


def get_risk_limits_keyboard(
    *,
    current_positions: int,
    current_size_usdt: Decimal,
    max_open_positions_ceiling: int,
    max_position_size_usdt_ceiling: Decimal,
) -> InlineKeyboardMarkup:
    """Return interactive buttons to adjust runtime risk limits."""
    # Row 1: Fine-tune positions
    row_pos: list[InlineKeyboardButton] = []
    if current_positions > 1:
        row_pos.append(
            InlineKeyboardButton("➖ 1 Pos", callback_data="cb_risk_pos_dec")
        )
    if current_positions < max_open_positions_ceiling:
        row_pos.append(
            InlineKeyboardButton("➕ 1 Pos", callback_data="cb_risk_pos_inc")
        )

    # Row 2: Fine-tune size
    row_size: list[InlineKeyboardButton] = []
    if current_size_usdt > Decimal("5"):
        row_size.append(
            InlineKeyboardButton("➖ $5 Size", callback_data="cb_risk_size_dec")
        )
    if current_size_usdt < max_position_size_usdt_ceiling:
        row_size.append(
            InlineKeyboardButton("➕ $5 Size", callback_data="cb_risk_size_inc")
        )

    # Row 3: Preset Positions (e.g. 1, 3, 5, 8, 10 up to ceiling)
    preset_pos = (1, 3, 5, 8, 10)
    row_preset_pos = [
        InlineKeyboardButton(
            f"📍 {p} Pos" if p == current_positions else f"{p} Pos",
            callback_data=f"cb_risk_set_pos_{p}",
        )
        for p in preset_pos
        if p <= max_open_positions_ceiling
    ]

    # Row 4: Preset Sizes (e.g. 10, 20, 50, 100 up to ceiling)
    preset_sizes = (10, 20, 50, 100)
    row_preset_size = [
        InlineKeyboardButton(
            f"💵 ${s}" if Decimal(s) == current_size_usdt else f"${s}",
            callback_data=f"cb_risk_set_size_{s}",
        )
        for s in preset_sizes
        if Decimal(s) <= max_position_size_usdt_ceiling
    ]

    # Nav Row
    row_nav = [
        InlineKeyboardButton("🔄 Refresh", callback_data="cb_risk_limits"),
        InlineKeyboardButton(f"◀️ {MENU_STATUS}", callback_data="cb_status"),
    ]

    rows: list[list[InlineKeyboardButton]] = []
    if row_pos:
        rows.append(row_pos)
    if row_size:
        rows.append(row_size)
    if row_preset_pos:
        rows.append(row_preset_pos)
    if row_preset_size:
        rows.append(row_preset_size)
    rows.append(row_nav)
    return InlineKeyboardMarkup(rows)


def get_main_menu_keyboard(
    *,
    execution_policy: ExecutionPolicy = ExecutionPolicy.SINGLE_SYMBOL,
    is_paused: bool = True,
) -> ReplyKeyboardMarkup:
    """Return a persistent menu whose controls match the active workflow."""
    if execution_policy is ExecutionPolicy.SINGLE_SYMBOL:
        return _get_reply_keyboard(
            [
                [MENU_DASHBOARD, MENU_TRADING],
                [MENU_CONFIGURATION, MENU_ACTIVITY],
                [MENU_TRADING_MODE],
            ]
        )

    runtime_action = MENU_RESUME if is_paused else MENU_PAUSE
    if execution_policy is ExecutionPolicy.AUTONOMOUS_LIVE:
        return _get_reply_keyboard(
            [
                [MENU_STATUS, MENU_POSITIONS],
                [MENU_STRATEGY, MENU_RISK_LIMITS],
                [MENU_ACTIVITY, MENU_TRADING_MODE],
                [runtime_action],
            ]
        )

    return _get_reply_keyboard(
        [
            [MENU_STATUS, MENU_POSITIONS],
            [MENU_STRATEGY, MENU_ACTIVITY],
            [runtime_action, MENU_TRADING_MODE],
        ]
    )


def get_operator_exit_positions_keyboard(
    *,
    positions: Sequence[Position],
) -> InlineKeyboardMarkup:
    """Return explicit per-position and whole-portfolio exit controls."""
    rows = [
        [
            InlineKeyboardButton(
                f"⚠️ Close {position.symbol.upper()}",
                callback_data=(
                    f"cb_operator_exit_close_{position.symbol.strip().lower()}"
                ),
            )
        ]
        for position in positions
    ]
    if positions:
        rows.append(
            [
                InlineKeyboardButton(
                    "⚠️ Close All Positions",
                    callback_data="cb_operator_exit_close_all",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def get_operator_exit_confirmation_keyboard(
    *,
    confirmation: OperatorExitConfirmation,
) -> InlineKeyboardMarkup:
    """Return safe confirmation controls without weakening MAINNET typing."""
    rows: list[list[InlineKeyboardButton]] = []
    if not confirmation.requires_typed_confirmation:
        rows.append(
            [
                InlineKeyboardButton(
                    "✅ Confirm Exit",
                    callback_data=(
                        f"cb_operator_exit_confirm_{confirmation.confirmation_id}"
                    ),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "Cancel",
                callback_data=(
                    f"cb_operator_exit_cancel_{confirmation.confirmation_id}"
                ),
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def get_operator_flatten_switch_keyboard(
    *,
    execution_policy: ExecutionPolicy,
) -> InlineKeyboardMarkup:
    """Offer an explicit financial transition when positions block switching."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⚠️ Close All & Switch",
                    callback_data=(
                        f"cb_operator_exit_flatten_switch_{execution_policy.value}"
                    ),
                )
            ],
            [InlineKeyboardButton("Cancel", callback_data="cb_policy_cancel")],
        ]
    )


def get_execution_policy_keyboard(
    *,
    current_policy: ExecutionPolicy,
    available_policies: Sequence[ExecutionPolicy],
) -> InlineKeyboardMarkup:
    """Return only workflows allowed by the immutable boot capability envelope."""
    rows = [
        [
            InlineKeyboardButton(
                (
                    f"{'✅ ' if policy is current_policy else ''}"
                    f"{_get_execution_policy_label(policy)}"
                ),
                callback_data=f"cb_policy_select_{policy.value}",
            )
        ]
        for policy in available_policies
    ]
    rows.append([InlineKeyboardButton("✖️ Close", callback_data="cb_policy_cancel")])
    return InlineKeyboardMarkup(rows)


def get_execution_policy_confirmation_keyboard(
    *,
    execution_policy: ExecutionPolicy,
) -> InlineKeyboardMarkup:
    """Require a second explicit action before committing a session restart."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm Switch",
                    callback_data=f"cb_policy_confirm_{execution_policy.value}",
                ),
                InlineKeyboardButton("Cancel", callback_data="cb_policy_cancel"),
            ]
        ]
    )


def _get_execution_policy_label(policy: ExecutionPolicy) -> str:
    """Return one compact operator-facing workflow label."""
    match policy:
        case ExecutionPolicy.SINGLE_SYMBOL:
            return "🎯 Single Symbol"
        case ExecutionPolicy.AUTONOMOUS_PAPER | ExecutionPolicy.AUTONOMOUS_LIVE:
            return "🤖 Auto Discovery"
        case ExecutionPolicy.HUMAN_CONFIRMED_PAPER:
            return "✅ Human Confirmed"


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
    """Get exchange selection inline keyboard."""

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
            InlineKeyboardButton(f"{spot_check}Spot", callback_data="cb_product_spot"),
            InlineKeyboardButton(
                f"{futures_check}Futures",
                callback_data="cb_product_futures",
            ),
        ],
        [InlineKeyboardButton("◀️ Back", callback_data="cb_back_main")],
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
        ("ADX Trend", "adx_trend"),
        ("Ichimoku Cloud", "ichimoku_cloud"),
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
