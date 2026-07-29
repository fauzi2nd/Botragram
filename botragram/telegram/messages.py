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
from botragram.exchanges.base.mapper import OrderResult, PositionInfo
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
        "Gunakan menu di bawah untuk memantau bot dan mengelola trading.\n\n"
        "⚠️ <b>Keamanan</b>\n"
        "Botragram tidak pernah meminta password, OTP, API key, atau secret "
        "melalui chat Telegram."
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


def get_exchange_message(current_exchange: str) -> str:
    """Get exchange selection message.

    Args:
        current_exchange: Currently active exchange name.

    Returns:
        Formatted HTML string.
    """
    exchange_info: dict[str, str] = {
        "BYBIT": "🟡 <b>Bybit</b> — Derivatives &amp; Spot",
        "BINANCE": "🟠 <b>Binance</b> — World's Largest Exchange",
        "OKX": "⚫ <b>OKX</b> — Advanced Trading Platform",
        "BITGET": "🔵 <b>Bitget</b> — Copy Trading Exchange",
    }
    desc = exchange_info.get(current_exchange.upper(), current_exchange)
    return (
        f"🔄 <b>Exchange Selection</b>\n\n"
        f"<b>Active:</b> {desc}\n\n"
        "Pilih exchange yang ingin digunakan:"
    )


def get_exchange_switched_message(new_exchange: str) -> str:
    """Get confirmation message after exchange switch.

    Args:
        new_exchange: Newly selected exchange name.

    Returns:
        Formatted HTML string.
    """
    return (
        f"✅ <b>Exchange berhasil diganti!</b>\n\n"
        f"<b>Sekarang menggunakan:</b> {new_exchange.upper()}\n\n"
        "Bot akan menggunakan credentials dari <code>.env</code> untuk exchange ini."
    )


def get_market_message(symbol: str, last_price: Decimal) -> str:
    """Get market status message."""
    return (
        "📈 <b>Market Data</b>\n\n"
        f"<b>Symbol:</b> {symbol}\n"
        f"<b>Last Price:</b> {format_currency(last_price, symbol='USDT')}\n"
        "\n" 
        "Data pasar diperbarui secara berkala dari exchange aktif."
    )


def get_orders_message(orders: list[OrderResult]) -> str:
    """Get active orders message."""
    if not orders:
        return "ℹ️ <b>No active open orders.</b>"

    lines: list[str] = ["📑 <b>Active Orders</b>\n"]
    for order in orders:
        lines.append(
            f"• <b>{order.symbol}</b> {order.side.value} {order.order_type.value} "
            f"qty={order.quantity} status={order.status.value}"
        )
    return "\n".join(lines)


def get_balance_message(balance_usdt: Decimal) -> str:
    """Get account balance summary message."""
    return (
        "💰 <b>Account Balance</b>\n\n"
        f"<b>Available:</b> {format_currency(balance_usdt, symbol='USDT')}\n"
        "\n"
        "Saldo ini berasal dari mode PAPER default."
    )


def get_history_message() -> str:
    """Get account history placeholder message."""
    return (
        "📜 <b>History</b>\n\n"
        "Riwayat trading dan order akan ditampilkan di sini ketika fitur tersedia."
    )


def get_strategy_message(strategy_name: str, fast_period: int, slow_period: int) -> str:
    """Get current strategy details message."""
    return (
        "🧠 <b>Strategy</b>\n\n"
        f"<b>Active Strategy:</b> {strategy_name}\n"
        f"<b>Fast EMA period:</b> {fast_period}\n"
        f"<b>Slow EMA period:</b> {slow_period}"
    )


def get_stream_message() -> str:
    """Get stream status placeholder message."""
    return (
        "📡 <b>Stream</b>\n\n"
        "Koneksi streaming belum diaktifkan di versi ini."
    )


def get_start_message(is_running: bool) -> str:
    """Get bot start confirmation message."""
    if is_running:
        return "▶️ <b>Bot sudah berjalan.</b>"
    return "▶️ <b>Bot trading telah dimulai kembali.</b>"


def get_pause_message(is_running: bool) -> str:
    """Get bot pause confirmation message."""
    if not is_running:
        return "⏸️ <b>Bot trading telah dijeda.</b>"
    return "⏸️ <b>Bot masih berjalan.</b>"


def get_test_message() -> str:
    """Get test mode message."""
    return (
        "🧪 <b>Test</b>\n\n"
        "Alur pengujian sementara belum diimplementasikan."
    )


def get_stop_message() -> str:
    """Get bot stop confirmation message."""
    return "❌ <b>Trading Bot telah dihentikan.</b>"
