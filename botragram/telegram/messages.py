"""
Botragram

Description:
    Telegram bot formatted message templates.

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
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.app import APP_NAME, APP_VERSION
from botragram.exchanges.base.mapper import PositionInfo
from botragram.utils.formatter import format_currency, format_percentage


# =============================================================================
# Message Templates
# =============================================================================
def get_welcome_message() -> str:
    """Get welcome message for /start command.

    Returns:
        Formatted HTML string.
    """
    return (
        f"🤖 <b>Welcome to {APP_NAME} v{APP_VERSION}</b>\n\n"
        "Trading Bot controls:\n"
        "• /status - View current bot & market status\n"
        "• /positions - View active open positions\n"
        "• /settings - View current bot settings\n"
        "• /stop - Gracefully pause bot trading"
    )


def get_status_message(
    is_running: bool,
    trade_mode: str,
    symbol: str,
    last_price: Decimal,
) -> str:
    """Get status message for /status command.

    Args:
        is_running: Engine running state boolean.
        trade_mode: Trade execution mode string.
        symbol: Active trading symbol.
        last_price: Current market price as Decimal.

    Returns:
        Formatted HTML string.
    """
    state_str = "🟢 RUNNING" if is_running else "🔴 STOPPED"
    price_str = format_currency(last_price, symbol="USDT")
    return (
        f"📊 <b>{APP_NAME} Status</b>\n\n"
        f"<b>State:</b> {state_str}\n"
        f"<b>Mode:</b> {trade_mode}\n"
        f"<b>Symbol:</b> {symbol}\n"
        f"<b>Last Price:</b> {price_str}"
    )


def get_positions_message(positions: list[PositionInfo]) -> str:
    """Get positions list message for /positions command.

    Args:
        positions: List of PositionInfo objects.

    Returns:
        Formatted HTML string.
    """
    if not positions:
        return "ℹ️ <b>No active open positions.</b>"

    lines: list[str] = ["💼 <b>Active Open Positions:</b>\n"]
    for pos in positions:
        pnl_str = format_percentage(pos.unrealized_pnl)
        lines.append(
            f"• <b>{pos.symbol}</b> ({pos.position_side.value}): "
            f"Size={pos.size}, Entry={pos.entry_price}, PnL={pnl_str}"
        )

    return "\n".join(lines)


def get_settings_message(
    exchange_type: str,
    strategy_name: str,
    trade_mode: str,
) -> str:
    """Get settings summary message for /settings command.

    Args:
        exchange_type: Exchange name string.
        strategy_name: Active strategy name.
        trade_mode: Execution mode string.

    Returns:
        Formatted HTML string.
    """
    return (
        f"⚙️ <b>{APP_NAME} Settings</b>\n\n"
        f"<b>Exchange:</b> {exchange_type}\n"
        f"<b>Strategy:</b> {strategy_name}\n"
        f"<b>Trade Mode:</b> {trade_mode}"
    )
