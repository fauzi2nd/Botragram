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
from botragram.enums import MarketType
from botragram.models import Order, Position, Trade
from botragram.utils.formatter import format_currency

__all__ = [
    "get_balance_message",
    "get_exchange_message",
    "get_exchange_switched_message",
    "get_history_message",
    "get_interval_message",
    "get_market_message",
    "get_navigation_message",
    "get_orders_message",
    "get_paper_entry_message",
    "get_paper_exit_message",
    "get_pause_message",
    "get_positions_message",
    "get_resume_message",
    "get_runtime_pause_message",
    "get_runtime_portfolio_message",
    "get_settings_message",
    "get_start_message",
    "get_status_message",
    "get_stop_message",
    "get_strategy_message",
    "get_stream_message",
    "get_startup_configuration_message",
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


def get_navigation_message(*, title: str, description: str) -> str:
    """Return one concise submenu introduction."""
    return (
        f"🧭 <b>{escape(title)}</b>\n\n"
        f"{escape(description)}\n\n"
        "Pilih aksi dari menu ringkas di bawah."
    )


def get_status_message(
    is_running: bool,
    trade_mode: str,
    symbol: str,
    last_price: Decimal,
    available_balance: Decimal | None = None,
    open_position_count: int | None = None,
    is_paused: bool = False,
    exchange_type: str | None = None,
    market_type: MarketType | None = None,
    strategy_name: str | None = None,
    interval: str | None = None,
    stream_active: bool | None = None,
    total_unrealized_pnl: Decimal | None = None,
) -> str:
    """Return a compact application, market, and portfolio control center."""
    if is_running and is_paused:
        state = "🟡 PAUSED"
    else:
        state = "🟢 RUNNING" if is_running else "🔴 STOPPED"
    if stream_active is None:
        stream = "⚪ UNKNOWN"
    else:
        stream = "🟢 LIVE" if stream_active else "⚪ OFFLINE"
    market = market_type.value.upper() if market_type is not None else "-"
    exchange = exchange_type.upper() if exchange_type else "-"
    strategy = strategy_name or "-"
    candle_interval = interval or "-"
    lines = [
        f"📊 <b>{APP_NAME.upper()} CONTROL CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{state}  ·  <b>{escape(trade_mode.upper())}</b>\n"
        f"🏦 {escape(exchange)} · {escape(market)}\n"
        f"📈 <b>{escape(symbol)}</b> · {escape(candle_interval)}\n"
        f"🧠 {escape(strategy)}\n"
        f"📡 Stream: {stream}\n\n"
        "<b>MARKET &amp; PORTFOLIO</b>\n"
        f"Price   <code>{format_currency(last_price, symbol='USDT')}</code>"
    ]

    if available_balance is not None:
        lines.append(
            "\nBalance <code>"
            f"{format_currency(available_balance, symbol='USDT')}</code>"
        )

    if open_position_count is not None:
        lines.append(f"\n<b>Open Positions:</b> {open_position_count}")

    if total_unrealized_pnl is not None:
        pnl_icon = "🟢" if total_unrealized_pnl >= 0 else "🔴"
        lines.append(
            f"\n{pnl_icon} <b>Unrealized PnL:</b> "
            f"{format_currency(total_unrealized_pnl, symbol='USDT')}"
        )

    return "".join(lines)


def get_positions_message(
    positions: Sequence[Position],
) -> str:
    """Return active trading positions."""
    if not positions:
        return "ℹ️ <b>Tidak ada posisi aktif.</b>"

    lines: list[str] = [
        f"💼 <b>ACTIVE POSITIONS · {len(positions)}</b>\n━━━━━━━━━━━━━━━━━━"
    ]

    for position in positions:
        side_icon = "🟢" if position.side.value == "long" else "🔴"
        lines.append(
            f"\n{side_icon} <b>{escape(position.symbol)}</b> · "
            f"{position.side.value.upper()} · {position.leverage}x\n"
            f"Qty={position.quantity}\n"
            f"Entry / Mark: {_format_optional_price(position.entry_price)} / "
            f"{_format_optional_price(position.current_price)}\n"
            f"SL / TP: {_format_optional_price(position.stop_loss)} / "
            f"{_format_optional_price(position.take_profit)}\n"
            f"PnL={format_currency(position.unrealized_pnl, symbol='USDT')} · "
            f"SL+ Step {position.protection_step}"
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
    market_type: MarketType = MarketType.SPOT,
) -> str:
    """Return the exchange selection message."""
    exchange_name = current_exchange.strip().upper()
    market_name = escape(market_type.value.title())
    exchange_info: dict[str, str] = {
        "BYBIT": "🟡 <b>Bybit</b> — Derivatives &amp; Spot",
        "BINANCE": f"🟠 <b>Binance</b> — {market_name} Exchange",
        "OKX": "⚫ <b>OKX</b> — Advanced Trading Platform",
        "BITGET": "🔵 <b>Bitget</b> — Copy Trading Exchange",
    }
    description = exchange_info.get(exchange_name, escape(exchange_name))

    return (
        "🔄 <b>Konfirmasi Exchange</b>\n\n"
        f"<b>Aktif:</b> {description}\n\n"
        "Konfirmasikan connector aktif. Mengganti exchange memerlukan profile "
        "environment lain dan restart aplikasi."
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
        return "ℹ️ <b>Tidak ada order tersimpan.</b>"

    lines: list[str] = ["📑 <b>Order Terbaru:</b>\n"]

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


def get_paper_entry_message(
    *,
    order: Order,
    trade: Trade,
    position: Position,
    available_balance: Decimal,
) -> str:
    """Return a safe paper-position entry notification."""
    return (
        "<b>Paper Entry</b>\n\n"
        f"<b>Symbol:</b> {escape(order.symbol)}\n"
        f"<b>Position:</b> {position.side.value.upper()}\n"
        f"<b>Quantity:</b> {order.executed_quantity}\n"
        f"<b>Fill:</b> {format_currency(trade.price, symbol='USDT')}\n"
        f"<b>Fee:</b> {format_currency(trade.fee, symbol=trade.fee_asset)}\n"
        f"<b>Stop Loss:</b> {_format_optional_price(position.stop_loss)}\n"
        f"<b>Take Profit:</b> {_format_optional_price(position.take_profit)}\n"
        f"<b>Available Balance:</b> "
        f"{format_currency(available_balance, symbol='USDT')}"
    )


def get_paper_exit_message(
    *,
    order: Order,
    trade: Trade,
    available_balance: Decimal,
    reason: str,
) -> str:
    """Return a safe paper-position exit notification."""
    realized_pnl = trade.realized_pnl or Decimal("0")

    return (
        "<b>Paper Exit</b>\n\n"
        f"<b>Symbol:</b> {escape(order.symbol)}\n"
        f"<b>Side:</b> {order.side.value}\n"
        f"<b>Quantity:</b> {order.executed_quantity}\n"
        f"<b>Fill:</b> {format_currency(trade.price, symbol='USDT')}\n"
        f"<b>Fee:</b> {format_currency(trade.fee, symbol=trade.fee_asset)}\n"
        f"<b>Realized PnL:</b> {format_currency(realized_pnl, symbol='USDT')}\n"
        f"<b>Available Balance:</b> "
        f"{format_currency(available_balance, symbol='USDT')}\n"
        f"<b>Reason:</b> {escape(reason)}"
    )


def _format_optional_price(value: Decimal | None) -> str:
    """Format an optional protective price for Telegram HTML."""
    if value is None:
        return "-"

    return format_currency(value, symbol="USDT")


def get_history_message(trades: Sequence[Trade] = ()) -> str:
    """Return recent persisted paper fills."""
    if not trades:
        return "📜 <b>History</b>\n\nBelum ada paper trade."

    lines = ["📜 <b>Paper Trade History</b>\n"]

    for trade in reversed(trades):
        pnl = (
            "-"
            if trade.realized_pnl is None
            else format_currency(trade.realized_pnl, symbol=trade.fee_asset)
        )
        lines.append(
            f"\n<b>{escape(trade.symbol)}</b> {trade.side.value} "
            f"qty={trade.quantity}\n"
            f"Fill={format_currency(trade.price, symbol=trade.fee_asset)} | "
            f"Fee={format_currency(trade.fee, symbol=trade.fee_asset)} | "
            f"PnL={pnl}\n"
            f"Time={escape(trade.executed_at.isoformat())}"
        )

    return "\n".join(lines)


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


def get_interval_message(interval: str) -> str:
    """Return the current runtime candle interval."""
    return (
        "⏱️ <b>Candle Interval</b>\n\n"
        f"<b>Active Interval:</b> {escape(interval)}\n\n"
        "Pilih interval yang akan digunakan pada siklus trading."
    )


def get_stream_message(
    *,
    transport_connected: bool,
    subscription_active: bool,
    first_tick_received: bool,
) -> str:
    """Return distinct WebSocket transport and subscription states."""
    transport = "READY" if transport_connected else "DISCONNECTED"
    subscription = "ACTIVE" if subscription_active else "INACTIVE"
    first_tick = "RECEIVED" if first_tick_received else "WAITING"
    return (
        "📡 <b>Market Stream</b>\n\n"
        f"<b>WebSocket Transport:</b> {transport}\n"
        f"<b>Market Subscription:</b> {subscription}\n"
        f"<b>First Tick:</b> {first_tick}\n\n"
        "Trading hanya dapat dimulai setelah subscription aktif dan tick "
        "pertama diterima."
    )


def get_startup_configuration_message(
    *,
    exchange: str,
    symbol: str,
    interval: str,
    strategy: str,
    missing_requirements: Sequence[str],
) -> str:
    """Return the Telegram-owned startup checklist."""
    missing = frozenset(missing_requirements)

    def _marker(requirement: str) -> str:
        return "⬜" if requirement in missing else "✅"

    first_tick_marker = (
        "⬜"
        if "stream subscription" in missing or "first stream tick" in missing
        else "✅"
    )

    return (
        "🧭 <b>Startup Configuration</b>\n\n"
        f"{_marker('exchange')} Exchange: {escape(exchange.upper())}\n"
        f"{_marker('symbol')} Symbol: {escape(symbol)}\n"
        f"{_marker('interval')} Interval: {escape(interval)}\n"
        f"{_marker('strategy')} Strategy: {escape(strategy)}\n"
        f"{_marker('stream subscription')} Stream subscription\n"
        f"{first_tick_marker} First stream tick\n\n"
        "Pilih konfigurasi dari menu Telegram secara berurutan, aktifkan "
        "Stream, lalu tekan Start Bot."
    )


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


def get_runtime_pause_message(*, changed: bool) -> str:
    """Return cooperative trading pause confirmation."""
    if changed:
        return "⏸️ <b>Trading berhasil dijeda.</b>"

    return "ℹ️ <b>Trading sudah dalam keadaan paused.</b>"


def get_resume_message(*, changed: bool) -> str:
    """Return cooperative trading resume confirmation."""
    if changed:
        return "▶️ <b>Trading berhasil dilanjutkan.</b>"

    return "ℹ️ <b>Trading sudah aktif.</b>"


def get_runtime_portfolio_message(
    *,
    available_balance: Decimal,
    positions: Sequence[Position],
    completed_cycles: int,
) -> str:
    """Return a periodic paper portfolio summary."""
    total_unrealized = sum(
        (position.unrealized_pnl for position in positions),
        start=Decimal("0"),
    )
    return (
        "<b>Periodic Paper Portfolio</b>\n\n"
        f"<b>Completed Cycles:</b> {completed_cycles}\n"
        f"<b>Available Balance:</b> "
        f"{format_currency(available_balance, symbol='USDT')}\n"
        f"<b>Open Positions:</b> {len(positions)}\n"
        f"<b>Unrealized PnL:</b> "
        f"{format_currency(total_unrealized, symbol='USDT')}"
    )


def get_test_message() -> str:
    """Return test mode placeholder."""
    return "🧪 <b>Test</b>\n\nAlur pengujian belum diimplementasikan."


def get_stop_message() -> str:
    """Return application stop confirmation."""
    return "❌ <b>Trading bot telah dihentikan.</b>"
