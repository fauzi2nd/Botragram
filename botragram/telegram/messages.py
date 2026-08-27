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
from botragram.enums import AuthorizationStatus, MarketType, SignalType
from botragram.models import (
    AutonomousLiveRecoverySnapshot,
    ExecutionAuthorization,
    ExecutionAuthorizationOutcome,
    LiveRuntimeHealthSnapshot,
    Order,
    Position,
    Trade,
)
from botragram.utils.formatter import format_currency

__all__ = [
    "get_balance_message",
    "get_autonomous_live_recovery_message",
    "get_exchange_message",
    "get_exchange_switched_message",
    "get_history_message",
    "get_live_runtime_health_message",
    "get_interval_message",
    "get_market_message",
    "get_market_overview_message",
    "get_market_search_prompt_message",
    "get_market_search_results_message",
    "get_navigation_message",
    "get_orders_message",
    "get_execution_authorization_message",
    "get_execution_authorization_outcome_message",
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
    symbol: str | None,
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
    missing_configuration_requirements: Sequence[str] = (),
    live_runtime_health: LiveRuntimeHealthSnapshot | None = None,
    autonomous_live_recovery: AutonomousLiveRecoverySnapshot | None = None,
) -> str:
    """Return a compact application, market, and portfolio control center."""
    multi_context_count = (
        len(live_runtime_health.contexts)
        if live_runtime_health is not None and len(live_runtime_health.contexts) > 1
        else None
    )
    is_multi_context_runtime = multi_context_count is not None
    configuration_requirements = frozenset(
        {"exchange", "market type", "symbol", "interval", "strategy"}
    )
    missing = frozenset(missing_configuration_requirements) & configuration_requirements
    if is_running and is_paused:
        state = "🟡 PAUSED"
    else:
        state = "🟢 RUNNING" if is_running else "🔴 STOPPED"
    if is_multi_context_runtime:
        stream = "MULTI-CONTEXT"
    elif stream_active is None:
        stream = "⚪ UNKNOWN"
    else:
        stream = "🟢 LIVE" if stream_active else "⚪ OFFLINE"
    market = (
        market_type.value.upper()
        if market_type is not None and "market type" not in missing
        else "BELUM DIPILIH"
    )
    exchange = (
        exchange_type.upper()
        if exchange_type and "exchange" not in missing
        else "BELUM DIPILIH"
    )
    selected_symbol = (
        symbol if symbol is not None and "symbol" not in missing else "BELUM DIPILIH"
    )
    strategy = (
        strategy_name
        if strategy_name and "strategy" not in missing
        else "BELUM DIPILIH"
    )
    candle_interval = (
        interval if interval and "interval" not in missing else "BELUM DIPILIH"
    )
    price = (
        format_currency(last_price, symbol="USDT")
        if not is_multi_context_runtime and "symbol" not in missing and last_price > 0
        else "WAITING"
    )
    if is_multi_context_runtime:
        configuration_summary = (
            f"📁 <b>Recovered LIVE Portfolio</b> · {multi_context_count} contexts\n"
            f"🧠 Strategy Type: {escape(strategy)}\n"
        )
    elif missing:
        configured_count = len(configuration_requirements) - len(missing)
        configuration_summary = (
            f"🧭 Setup: <b>{configured_count}/5 · INCOMPLETE</b>\n"
            "ℹ️ Lanjutkan melalui menu Configuration\n"
        )
    else:
        configuration_summary = (
            f"🏦 {escape(exchange)} · {escape(market)}\n"
            f"📈 <b>{escape(selected_symbol)}</b> · "
            f"{escape(candle_interval)}\n"
            f"🧠 Strategy Type: {escape(strategy)}\n"
        )
    lines = [
        f"📊 <b>{APP_NAME.upper()} CONTROL CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{state}  ·  <b>{escape(trade_mode.upper())}</b>\n"
        f"{configuration_summary}"
        f"📡 Stream: {stream}\n\n"
        "<b>MARKET &amp; PORTFOLIO</b>\n"
        f"Price   <code>{price}</code>"
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

    if live_runtime_health is not None:
        lines.append(get_live_runtime_health_message(snapshot=live_runtime_health))
    if autonomous_live_recovery is not None:
        lines.append(
            get_autonomous_live_recovery_message(snapshot=autonomous_live_recovery)
        )

    return "".join(lines)


def get_autonomous_live_recovery_message(
    *, snapshot: AutonomousLiveRecoverySnapshot
) -> str:
    """Render durable autonomous recovery state without controls or mutation."""
    entry_environment = (
        snapshot.autonomous_entry_environment.value.upper()
        if snapshot.autonomous_entry_environment is not None
        else "TESTNET"
    )
    entry_state = (
        f"ENABLED — {entry_environment}"
        if snapshot.autonomous_entry_authorized
        else "DISABLED"
    )
    new_entry_state = (
        "BLOCKED"
        if snapshot.new_entry_blocked_by_recovery
        else "NOT BLOCKED BY RECOVERY"
    )
    lines = [
        "\n\n<b>AUTONOMOUS LIVE RECOVERY</b>\n",
        f"Status: <b>{escape(snapshot.status.value.upper())}</b>\n",
        f"Autonomous Entry: <b>{entry_state}</b>\n",
        f"New Entry: <b>{new_entry_state}</b>\n",
    ]
    if snapshot.reason is not None:
        lines.append(f"Reason: <b>{escape(snapshot.reason.value.upper())}</b>\n")
    if snapshot.incomplete_attempt_count:
        lines.append(f"Incomplete Attempts: {snapshot.incomplete_attempt_count}\n")
    if snapshot.attempt_status is not None:
        lines.append(f"Attempt: {escape(snapshot.attempt_status.value.upper())}\n")
    if snapshot.symbol is not None:
        lines.append(f"Symbol: {escape(snapshot.symbol)}\n")
    return "".join(lines)


def get_live_runtime_health_message(*, snapshot: LiveRuntimeHealthSnapshot) -> str:
    """Render one immutable recovered LIVE health snapshot without controls."""
    lines = [
        "\n\n<b>RECOVERED LIVE RUNTIME</b>\n",
        f"Status: <b>{escape(snapshot.status.value.upper())}</b>\n",
        f"Contexts: {len(snapshot.contexts)}\n",
        "Management Authorization: "
        f"{'EXACT' if snapshot.authorization_exact else 'UNAVAILABLE'}\n",
        "New LIVE Exposure: <b>DISABLED</b>\n",
    ]
    if snapshot.reason is not None:
        lines.append(f"Reason: <b>{escape(snapshot.reason.value.upper())}</b>\n")
    for context in snapshot.contexts:
        stream = next(
            (
                state
                for state in snapshot.stream_states
                if state.identity.symbol == context.symbol
                and state.identity.interval == context.interval
            ),
            None,
        )
        monitor = next(
            (state for state in snapshot.monitor_states if state.context == context),
            None,
        )
        stream_text = (
            stream.lifecycle_status.value.upper() if stream is not None else "MISSING"
        )
        monitor_text = (
            "HEALTHY"
            if monitor is not None and monitor.failure_type is None
            else "UNHEALTHY"
        )
        lines.append(
            f"\n<b>{escape(context.symbol)}</b> · {escape(context.interval.value)}"
            f" · {escape(context.strategy_type.value)}\n"
            f"Stream: {escape(stream_text)} · Monitor: {escape(monitor_text)}"
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
    *,
    exchange_confirmed: bool = False,
    market_type_confirmed: bool = False,
) -> str:
    """Return the exchange selection message."""
    exchange_name = current_exchange.strip().upper()
    exchange_info: dict[str, str] = {
        "BYBIT": "🟡 <b>Bybit</b>",
        "BINANCE": "🟠 <b>Binance</b>",
        "OKX": "⚫ <b>OKX</b>",
        "BITGET": "🔵 <b>Bitget</b>",
    }
    exchange = (
        exchange_info.get(exchange_name, escape(exchange_name))
        if exchange_confirmed
        else "Belum dipilih"
    )
    product = (
        escape(market_type.value.title()) if market_type_confirmed else "Belum dipilih"
    )

    return (
        "🔄 <b>Exchange &amp; Product</b>\n\n"
        f"<b>Exchange:</b> {exchange}\n"
        f"<b>Product:</b> {product}\n\n"
        "Pilih Spot atau Futures. Botragram akan menutup connector lama dan "
        "melakukan soft restart otomatis setelah pemeriksaan keamanan."
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
    *,
    confirmed: bool = False,
) -> str:
    """Return current market summary."""
    selected_symbol = escape(symbol) if confirmed else "Belum dipilih"
    price = (
        format_currency(last_price, symbol="USDT")
        if confirmed and last_price > 0
        else "WAITING"
    )
    return (
        "📈 <b>Market Data</b>\n\n"
        f"<b>Symbol:</b> {selected_symbol}\n"
        f"<b>Last Price:</b> {price}\n\n"
        "Data pasar diperbarui dari exchange aktif."
    )


def get_market_overview_message(
    *,
    symbol: str,
    last_price: Decimal,
    confirmed: bool,
) -> str:
    """Return a read-only market summary for the Dashboard menu."""
    if not confirmed:
        return (
            "📈 <b>Market Overview</b>\n\n"
            "🧭 Market belum dikonfigurasi.\n\n"
            "Buka <b>Configuration → Select Market</b> untuk memilih symbol."
        )

    return get_market_message(symbol, last_price, confirmed=True)


def get_market_search_prompt_message() -> str:
    """Return instructions for an exchange-symbol search."""
    return (
        "🔎 <b>Search Market</b>\n\n"
        "Ketik symbol atau kode koin yang ingin dicari.\n"
        "Contoh: <code>BTC</code>, <code>ETH</code>, atau <code>SOLUSDT</code>."
    )


def get_market_search_results_message(
    *,
    keyword: str,
    result_count: int,
    total_matches: int,
) -> str:
    """Return a concise exchange-symbol search summary."""
    if total_matches == 0:
        return (
            "🔎 <b>Market Search</b>\n\n"
            f"Tidak ada symbol yang cocok dengan <code>{escape(keyword)}</code>.\n"
            "Coba kode koin lain."
        )

    return (
        "🔎 <b>Market Search</b>\n\n"
        f"Keyword: <code>{escape(keyword)}</code>\n"
        f"Menampilkan {result_count} dari {total_matches} hasil.\n\n"
        "Pilih symbol yang ingin digunakan."
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


def get_execution_authorization_message(
    authorization: ExecutionAuthorization,
) -> str:
    """Render a prepared PAPER opportunity without recalculating trade data."""
    signal = authorization.signal
    intent = "LONG" if signal.signal_type is SignalType.BUY else "SHORT"
    reason = f"\n<b>Signal Note:</b> {escape(signal.reason)}" if signal.reason else ""

    return (
        "<b>Paper Opportunity Approval</b>\n\n"
        "<b>Environment:</b> PAPER\n"
        f"<b>Status:</b> {escape(authorization.status.value.upper())}\n"
        f"<b>Symbol:</b> {escape(signal.symbol)}\n"
        f"<b>Intent:</b> {intent}\n"
        f"<b>Strategy:</b> {escape(signal.strategy_name)}\n"
        f"<b>Confidence:</b> {signal.confidence:.2%}\n"
        f"<b>Reference Price:</b> {format_currency(signal.price, symbol='USDT')}\n"
        f"<b>Generated:</b> {escape(signal.generated_at.isoformat())}\n"
        f"<b>Expires:</b> {escape(authorization.expires_at.isoformat())}"
        f"{reason}\n\n"
        "Approve triggers final PAPER portfolio validation."
    )


def get_execution_authorization_outcome_message(
    outcome: ExecutionAuthorizationOutcome,
) -> str:
    """Render one authorization outcome without exposing internal exceptions."""
    authorization = outcome.authorization
    result = outcome.trading_result

    if result is not None and result.executed:
        symbol = escape(result.decision.signal.symbol)
        return (
            "<b>Paper Opportunity Executed</b>\n\n"
            f"<b>Symbol:</b> {symbol}\n"
            "<b>Environment:</b> PAPER\n"
            "Final portfolio validation passed."
        )

    if authorization is None:
        return "<b>Opportunity Unavailable</b>\n\nAuthorization was not found."

    if authorization.status is AuthorizationStatus.EXPIRED:
        return "<b>Opportunity Expired</b>\n\nRequest a fresh opportunity."

    if authorization.status is AuthorizationStatus.REJECTED:
        return "<b>Opportunity Rejected</b>\n\nNo PAPER trade was submitted."

    if authorization.status is AuthorizationStatus.APPROVED and result is None:
        return (
            "<b>Opportunity Already Processed</b>\n\n"
            "No additional PAPER trade was submitted."
        )

    if result is not None:
        reason = escape(
            outcome.reason or result.reason or "Final validation rejected it"
        )
        return (
            "<b>Paper Opportunity Not Executed</b>\n\n"
            f"<b>Reason:</b> {reason}\n"
            "No PAPER trade was submitted."
        )

    return (
        "<b>Opportunity Already Processed</b>\n\n"
        "No additional PAPER trade was submitted."
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
    *,
    confirmed: bool = False,
) -> str:
    """Return current strategy details."""
    if not confirmed:
        return (
            "🧠 <b>Strategy</b>\n\n"
            "<b>Strategy:</b> Belum dipilih\n\n"
            "Pilih strategy yang akan digunakan pada siklus trading."
        )

    return (
        "🧠 <b>Strategy</b>\n\n"
        f"<b>Strategy:</b> {escape(strategy_name)}\n"
        f"<b>Fast EMA period:</b> {fast_period}\n"
        f"<b>Slow EMA period:</b> {slow_period}"
    )


def get_interval_message(interval: str, *, confirmed: bool = False) -> str:
    """Return the current runtime candle interval."""
    selected_interval = escape(interval) if confirmed else "Belum dipilih"
    return (
        "⏱️ <b>Candle Interval</b>\n\n"
        f"<b>Interval:</b> {selected_interval}\n\n"
        "Pilih interval yang akan digunakan pada siklus trading."
    )


def get_stream_message(
    *,
    transport_connected: bool,
    subscription_active: bool,
    first_tick_received: bool,
    last_price: Decimal | None = None,
) -> str:
    """Return distinct WebSocket transport and subscription states."""
    transport = "READY" if transport_connected else "DISCONNECTED"
    subscription = "ACTIVE" if subscription_active else "INACTIVE"
    first_tick = "RECEIVED" if first_tick_received else "WAITING"
    price = (
        format_currency(last_price, symbol="USDT")
        if last_price is not None and last_price > 0
        else "WAITING"
    )
    return (
        "📡 <b>Market Stream</b>\n\n"
        f"<b>WebSocket Transport:</b> {transport}\n"
        f"<b>Market Subscription:</b> {subscription}\n"
        f"<b>First Tick:</b> {first_tick}\n\n"
        f"<b>Last Price:</b> {price}\n\n"
        "Trading hanya dapat dimulai setelah subscription aktif dan tick "
        "pertama diterima."
    )


def get_startup_configuration_message(
    *,
    exchange: str,
    market_type: str,
    symbol: str,
    interval: str,
    strategy: str,
    missing_requirements: Sequence[str],
) -> str:
    """Return the Telegram-owned startup checklist."""
    missing = frozenset(missing_requirements)

    def _marker(requirement: str) -> str:
        return "⬜" if requirement in missing else "✅"

    def _selection(requirement: str, value: str) -> str:
        return "BELUM DIPILIH" if requirement in missing else escape(value)

    first_tick_marker = (
        "⬜"
        if "stream subscription" in missing or "first stream tick" in missing
        else "✅"
    )

    return (
        "🧭 <b>Startup Configuration</b>\n\n"
        f"{_marker('exchange')} Exchange: "
        f"{_selection('exchange', exchange.upper())}\n"
        f"{_marker('market type')} Product: "
        f"{_selection('market type', market_type.upper())}\n"
        f"{_marker('symbol')} Symbol: {_selection('symbol', symbol)}\n"
        f"{_marker('interval')} Interval: {_selection('interval', interval)}\n"
        f"{_marker('strategy')} Strategy: {_selection('strategy', strategy)}\n"
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
