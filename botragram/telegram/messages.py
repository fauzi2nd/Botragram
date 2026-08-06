"""
Botragram

Description:
    Telegram bot HTML message templates.

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
from decimal import Decimal
from html import escape

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.app import APP_NAME, APP_VERSION
from botragram.models import Order, Position
from botragram.utils.formatter import format_currency

__all__ = [
    "get_balance_message",
    "get_exchange_message",
    "get_exchange_switched_message",
    "get_history_message",
    "get_market_message",
    "get_orders_message",
    "get_pause_message",
    "get_positions_message",
    "get_settings_message",
    "get_start_message",
    "get_status_message",
    "get_stop_message",
    "get_strategy_message",
    "get_stream_message",
    "get_test_message",
    "get_welcome_message",
]


# =============================================================================
# Message Templates
# =============================================================================
def get_welcome_message() -> str:
    """Return the welcome and security notice message."""
    return (
        f"🤖 <b>Selamat datang di {APP_NAME} v{APP_VERSION}</b>\n\n"
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
    """Return current application and market status."""
    state = "🟢 RUNNING" if is_running else "🔴 STOPPED"

    return (
        f"📊 <b>{APP_NAME} Status</b>\n\n"
        f"<b>State:</b> {state}\n"
        f"<b>Mode:</b> {escape(trade_mode)}\n"
        f"<b>Symbol:</b> {escape(symbol)}\n"
        f"<b>Last Price:</b> {format_currency(last_price, symbol='USDT')}"
    )


def get_positions_message(
    positions: Sequence[Position],
) -> str:
    """Return active trading positions."""
    if not positions:
        return "ℹ️ <b>Tidak ada posisi aktif.</b>"

    lines: list[str] = ["💼 <b>Posisi Aktif:</b>\n"]

    for position in positions:
        lines.append(
            f"• <b>{escape(position.symbol)}</b> ({position.side.value}): "
            f"Qty={position.quantity}, Entry={position.entry_price}, "
            f"PnL={format_currency(position.unrealized_pnl, symbol='USDT')}"
        )

    return "\n".join(lines)


def get_settings_message(
    exchange_type: str,
    strategy_name: str,
    trade_mode: str,
) -> str:
    """Return current exchange, strategy, and trade mode settings."""
    return (
        f"⚙️ <b>{APP_NAME} Settings</b>\n\n"
        f"<b>Exchange:</b> {escape(exchange_type)}\n"
        f"<b>Strategy:</b> {escape(strategy_name)}\n"
        f"<b>Trade Mode:</b> {escape(trade_mode)}"
    )


def get_exchange_message(
    current_exchange: str,
) -> str:
    """Return the exchange selection message."""
    exchange_name = current_exchange.strip().upper()
    exchange_info: dict[str, str] = {
        "BYBIT": "🟡 <b>Bybit</b> — Derivatives &amp; Spot",
        "BINANCE": "🟠 <b>Binance</b> — Spot Exchange",
        "OKX": "⚫ <b>OKX</b> — Advanced Trading Platform",
        "BITGET": "🔵 <b>Bitget</b> — Copy Trading Exchange",
    }
    description = exchange_info.get(exchange_name, escape(exchange_name))

    return (
        "🔄 <b>Pemilihan Exchange</b>\n\n"
        f"<b>Aktif:</b> {description}\n\n"
        "Pilih exchange yang ingin digunakan:"
    )


def get_exchange_switched_message(
    new_exchange: str,
) -> str:
    """Return confirmation after an exchange switch."""
    return (
        "✅ <b>Exchange berhasil diganti.</b>\n\n"
        f"<b>Sekarang menggunakan:</b> {escape(new_exchange.upper())}"
    )


def get_market_message(
    symbol: str,
    last_price: Decimal,
) -> str:
    """Return current market summary."""
    return (
        "📈 <b>Market Data</b>\n\n"
        f"<b>Symbol:</b> {escape(symbol)}\n"
        f"<b>Last Price:</b> {format_currency(last_price, symbol='USDT')}\n\n"
        "Data pasar diperbarui dari exchange aktif."
    )


def get_orders_message(
    orders: Sequence[Order],
) -> str:
    """Return active trading orders."""
    if not orders:
        return "ℹ️ <b>Tidak ada order aktif.</b>"

    lines: list[str] = ["📑 <b>Order Aktif:</b>\n"]

    for order in orders:
        lines.append(
            f"• <b>{escape(order.symbol)}</b> {order.side.value} "
            f"{order.order_type.value} qty={order.quantity} "
            f"status={order.status.value}"
        )

    return "\n".join(lines)


def get_balance_message(
    balance_usdt: Decimal,
) -> str:
    """Return account balance summary."""
    return (
        "💰 <b>Account Balance</b>\n\n"
        f"<b>Available:</b> {format_currency(balance_usdt, symbol='USDT')}"
    )


def get_history_message() -> str:
    """Return trading history placeholder."""
    return "📜 <b>History</b>\n\nRiwayat trading belum tersedia."


def get_strategy_message(
    strategy_name: str,
    fast_period: int,
    slow_period: int,
) -> str:
    """Return current strategy details."""
    return (
        "🧠 <b>Strategy</b>\n\n"
        f"<b>Active Strategy:</b> {escape(strategy_name)}\n"
        f"<b>Fast EMA period:</b> {fast_period}\n"
        f"<b>Slow EMA period:</b> {slow_period}"
    )


def get_stream_message() -> str:
    """Return streaming status placeholder."""
    return "📡 <b>Stream</b>\n\nStatus streaming belum tersedia."


def get_start_message(
    is_running: bool,
) -> str:
    """Return application start status."""
    if is_running:
        return "▶️ <b>Bot sudah berjalan.</b>"

    return "▶️ <b>Bot trading telah dimulai.</b>"


def get_pause_message(
    is_running: bool,
) -> str:
    """Return application pause status."""
    if not is_running:
        return "⏸️ <b>Bot trading telah dijeda.</b>"

    return "⏸️ <b>Bot masih berjalan.</b>"


def get_test_message() -> str:
    """Return test mode placeholder."""
    return "🧪 <b>Test</b>\n\nAlur pengujian belum diimplementasikan."


def get_stop_message() -> str:
    """Return application stop confirmation."""
    return "❌ <b>Trading bot telah dihentikan.</b>"
