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
from botragram.constants.strategy import (
    get_strategy_default_exit_rates,
    get_strategy_default_interval,
)
from botragram.enums import (
    AuthorizationStatus,
    LiveRuntimeHealthStatus,
    MarketType,
    SignalType,
    StrategyType,
)
from botragram.models import (
    AutonomousLiveRecoverySnapshot,
    ClosedPositionLifecycle,
    ExecutionAuthorization,
    ExecutionAuthorizationOutcome,
    LiveRuntimeHealthSnapshot,
    Order,
    Position,
    RuntimeRiskLimits,
    Trade,
)
from botragram.utils.formatter import format_currency, format_price

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
    "get_risk_limits_message",
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
    "get_tpsl_ratio_message",
    "get_trade_completed_message",
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
    autonomous_live: bool = False,
    max_open_positions: int | None = None,
    position_protection_ready: bool | None = None,
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
    if autonomous_live:
        stream = "RUNTIME-MANAGED"
    elif is_multi_context_runtime:
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
        if strategy_name and (autonomous_live or "strategy" not in missing)
        else "BELUM DIPILIH"
    )
    candle_interval = (
        interval
        if interval and (autonomous_live or "interval" not in missing)
        else "BELUM DIPILIH"
    )
    price = (
        "GLOBAL DISCOVERY"
        if autonomous_live
        else format_price(last_price, symbol="USDT")
        if not is_multi_context_runtime and "symbol" not in missing and last_price > 0
        else "WAITING"
    )
    autonomous_environment = (
        autonomous_live_recovery.autonomous_entry_environment.value.upper()
        if autonomous_live_recovery is not None
        and autonomous_live_recovery.autonomous_entry_environment is not None
        else "LIVE"
    )
    if autonomous_live:
        configuration_summary = (
            f"🤖 <b>Autonomous LIVE</b> · {escape(autonomous_environment)}\n"
            f"🏦 {escape(exchange)} · {escape(market)}\n"
            f"🌐 Discovery: GLOBAL · {escape(candle_interval)}\n"
            f"🧠 Strategy Type: {escape(strategy)}\n"
        )
    elif is_multi_context_runtime:
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
        lines.append(
            get_live_runtime_health_message(
                snapshot=live_runtime_health,
                new_live_exposure_state=_get_new_live_exposure_state(
                    autonomous_live=autonomous_live,
                    is_paused=is_paused,
                    open_position_count=open_position_count,
                    max_open_positions=max_open_positions,
                    position_protection_ready=position_protection_ready,
                    live_runtime_health=live_runtime_health,
                    autonomous_live_recovery=autonomous_live_recovery,
                ),
            )
        )
    if autonomous_live_recovery is not None:
        lines.append(
            get_autonomous_live_recovery_message(snapshot=autonomous_live_recovery)
        )

    return "".join(lines)


def _get_new_live_exposure_state(
    *,
    autonomous_live: bool,
    is_paused: bool,
    open_position_count: int | None,
    max_open_positions: int | None,
    position_protection_ready: bool | None,
    live_runtime_health: LiveRuntimeHealthSnapshot | None,
    autonomous_live_recovery: AutonomousLiveRecoverySnapshot | None,
) -> str:
    """Return one fail-closed operator state for future autonomous exposure."""
    if not autonomous_live:
        return "DISABLED"
    recovery = autonomous_live_recovery
    if recovery is None or not recovery.autonomous_entry_authorized:
        return "DISABLED"
    if recovery.new_entry_blocked_by_recovery:
        return "BLOCKED - RECOVERY"
    if open_position_count is None or max_open_positions is None:
        return "BLOCKED - LIMITS"
    if open_position_count >= max_open_positions:
        return "BLOCKED - CAPACITY"
    if is_paused:
        return "BLOCKED - PAUSED"
    if position_protection_ready is not True:
        return "BLOCKED - PROTECTION"

    health = live_runtime_health
    if health is None:
        return "BLOCKED - HEALTH"
    if open_position_count != len(health.contexts):
        return "BLOCKED - HEALTH"
    if health.contexts and not (
        health.status is LiveRuntimeHealthStatus.ACTIVE
        and health.authorization_present
        and health.authorization_exact
    ):
        return "BLOCKED - HEALTH"

    environment = (
        recovery.autonomous_entry_environment.value.upper()
        if recovery.autonomous_entry_environment is not None
        else "LIVE"
    )
    return f"ENABLED - {environment}"


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


def get_live_runtime_health_message(
    *,
    snapshot: LiveRuntimeHealthSnapshot,
    new_live_exposure_state: str = "DISABLED",
) -> str:
    """Render one immutable recovered LIVE health snapshot without controls."""
    lines = [
        "\n\n<b>RECOVERED LIVE RUNTIME</b>\n",
        f"Status: <b>{escape(snapshot.status.value.upper())}</b>\n",
        f"Contexts: {len(snapshot.contexts)}\n",
        "Management Authorization: "
        f"{'EXACT' if snapshot.authorization_exact else 'UNAVAILABLE'}\n",
        f"New LIVE Exposure: <b>{escape(new_live_exposure_state)}</b>\n",
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
        roi_str = ""
        notional = position.entry_price * position.quantity
        if notional > Decimal("0"):
            margin = notional / Decimal(str(max(position.leverage, 1)))
            if margin > Decimal("0"):
                roi_val = (position.unrealized_pnl / margin) * Decimal("100")
                sign = "+" if roi_val > Decimal("0") else ""
                roi_str = f" ({sign}{roi_val:.2f}%)"

        qty_str = format_price(position.quantity, min_decimals=0)
        lines.append(
            f"\n{side_icon} <b>{escape(position.symbol)}</b> · "
            f"{position.side.value.upper()} · {position.leverage}x\n"
            f"Qty={qty_str}\n"
            f"Entry / Mark: {_format_optional_price(position.entry_price)} / "
            f"{_format_optional_price(position.current_price)}\n"
            f"SL / TP: {_format_optional_price(position.stop_loss)} / "
            f"{_format_optional_price(position.take_profit)}\n"
            f"PnL={format_currency(position.unrealized_pnl, symbol='USDT')}{roi_str} · "
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
        format_price(last_price, symbol="USDT")
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
        f"<b>Fill:</b> {format_price(trade.price, symbol='USDT')}\n"
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
        f"<b>Fill:</b> {format_price(trade.price, symbol='USDT')}\n"
        f"<b>Fee:</b> {format_currency(trade.fee, symbol=trade.fee_asset)}\n"
        f"<b>Realized PnL:</b> {format_currency(realized_pnl, symbol='USDT')}\n"
        f"<b>Available Balance:</b> "
        f"{format_currency(available_balance, symbol='USDT')}\n"
        f"<b>Reason:</b> {escape(reason)}"
    )


def get_trade_completed_message(
    *,
    lifecycle: ClosedPositionLifecycle,
    entry_fills: Sequence[Trade] | None = None,
    exit_fills: Sequence[Trade] | None = None,
) -> str:
    """Return a detailed live trade completion summary formatted for Telegram."""
    ownership = lifecycle.ownership
    pnl = lifecycle.net_pnl
    pnl_sign = "+" if pnl > Decimal("0") else ""
    pnl_icon = "🟢" if pnl > Decimal("0") else ("🔴" if pnl < Decimal("0") else "⚪")
    outcome = (
        "WIN"
        if pnl > Decimal("0")
        else ("LOSS" if pnl < Decimal("0") else "BREAK-EVEN")
    )

    entry_price_str = "N/A"
    exit_price_str = "N/A"
    quantity_str = "N/A"

    if entry_fills:
        total_qty = sum((f.quantity for f in entry_fills), start=Decimal("0"))
        if total_qty > Decimal("0"):
            total_cost = sum(
                (f.price * f.quantity for f in entry_fills),
                start=Decimal("0"),
            )
            avg_entry = total_cost / total_qty
            entry_price_str = format_price(avg_entry, symbol="USDT")
            quantity_str = (
                f"{total_qty.normalize():f}"
                if total_qty == total_qty.to_integral()
                else f"{total_qty}"
            )

    if exit_fills:
        total_qty = sum((f.quantity for f in exit_fills), start=Decimal("0"))
        if total_qty > Decimal("0"):
            total_revenue = sum(
                (f.price * f.quantity for f in exit_fills),
                start=Decimal("0"),
            )
            avg_exit = total_revenue / total_qty
            exit_price_str = format_price(avg_exit, symbol="USDT")

    formatted_gross = format_currency(
        lifecycle.gross_realized_pnl,
        symbol=lifecycle.fee_asset,
    )
    formatted_fee = format_currency(
        lifecycle.fee,
        symbol=lifecycle.fee_asset,
    )
    formatted_net = format_currency(
        lifecycle.net_pnl,
        symbol=lifecycle.fee_asset,
    )

    formatted_closed_at = escape(lifecycle.closed_at.strftime("%Y-%m-%d %H:%M:%S UTC"))

    return (
        f"{pnl_icon} <b>Trade Completed ({outcome})</b>\n\n"
        f"<b>Symbol:</b> {escape(ownership.symbol)}\n"
        f"<b>Side:</b> {escape(ownership.position_side.value.upper())}\n"
        f"<b>Close Reason:</b> {escape(ownership.close_reason.value.upper())}\n"
        f"<b>Quantity:</b> {escape(quantity_str)}\n"
        f"<b>Entry Price:</b> {entry_price_str}\n"
        f"<b>Exit Price:</b> {exit_price_str}\n"
        f"<b>Gross PnL:</b> {formatted_gross}\n"
        f"<b>Fee:</b> {formatted_fee}\n"
        f"<b>Net Realized PnL:</b> <b>{pnl_sign}{formatted_net}</b>\n"
        f"<b>Closed At:</b> {formatted_closed_at}"
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
        f"<b>Reference Price:</b> {format_price(signal.price, symbol='USDT')}\n"
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

    return format_price(value)


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
            f"Fill={format_price(trade.price, symbol=trade.fee_asset)} | "
            f"Fee={format_currency(trade.fee, symbol=trade.fee_asset)} | "
            f"PnL={pnl}\n"
            f"Time={escape(trade.executed_at.isoformat())}"
        )

    return "\n".join(lines)


def get_strategy_message(
    strategy_name: str,
    fast_period: int = 9,
    slow_period: int = 21,
    *,
    confirmed: bool = False,
) -> str:
    """Return current strategy details formatted for Telegram."""
    if not confirmed:
        return (
            "🧠 <b>Strategy</b>\n\n"
            "<b>Strategy:</b> Belum dipilih\n\n"
            "Pilih strategy yang akan digunakan pada siklus trading."
        )

    escaped_name = escape(strategy_name)
    try:
        strategy_type = StrategyType(strategy_name.casefold())
    except ValueError:
        strategy_type = None

    lines = [
        "🧠 <b>Strategy</b>\n",
        f"<b>Strategy:</b> {escaped_name}",
    ]

    match strategy_type:
        case StrategyType.EMA_CROSS:
            lines.append(f"<b>Fast EMA period:</b> {fast_period}")
            lines.append(f"<b>Slow EMA period:</b> {slow_period}")
        case StrategyType.EMA_SCALPING:
            lines.append(f"<b>Fast EMA period:</b> {fast_period}")
            lines.append(f"<b>Slow EMA period:</b> {slow_period}")
        case StrategyType.EMA_RSI:
            lines.append(f"<b>Fast EMA period:</b> {fast_period}")
            lines.append(f"<b>Slow EMA period:</b> {slow_period}")
            lines.append("<b>RSI Period:</b> 14")
        case StrategyType.MACD_SWING:
            lines.append("<b>Fast period:</b> 12")
            lines.append("<b>Slow period:</b> 26")
            lines.append("<b>Signal period:</b> 9")
        case StrategyType.SUPERTREND:
            lines.append("<b>ATR period:</b> 10")
            lines.append("<b>Multiplier:</b> 3.0")
        case StrategyType.BOLLINGER_BREAKOUT:
            lines.append("<b>Period:</b> 20")
            lines.append("<b>StdDev:</b> 2.0")
        case StrategyType.ADX_TREND:
            lines.append("<b>ADX period:</b> 14")
            lines.append("<b>ADX threshold:</b> 25.0")
        case StrategyType.ICHIMOKU_CLOUD:
            lines.append("<b>Conversion period:</b> 9")
            lines.append("<b>Base period:</b> 26")
            lines.append("<b>Span B period:</b> 52")
        case StrategyType.RSI_BB_SCALPING:
            lines.append("<b>RSI period:</b> 14 (30/70)")
            lines.append("<b>BB period:</b> 20 (StdDev: 2.0)")
        case StrategyType.VWAP_BREAKOUT:
            lines.append("<b>VWAP:</b> Volume Weighted Avg Price")
            lines.append("<b>ATR period:</b> 14")
            lines.append("<b>Volume multiplier:</b> 1.2x")
        case StrategyType.CHOCH_FVG:
            lines.append("<b>Concept:</b> Smart Money (CHoCH + FVG)")
            lines.append("<b>Swing Window:</b> 5")
            lines.append("<b>Volume Multiplier:</b> 1.2x")
        case StrategyType.CHOCH_RSI_BB_HYBRID:
            lines.append("<b>Concept:</b> SMC Structure + RSI/BB Hybrid")
            lines.append("<b>Structure:</b> CHoCH + FVG Context")
            lines.append("<b>Trigger:</b> BB Extremity + RSI Rejection")
            lines.append("<b>Risk:</b> DynATR + Anti-Churn Cooldown")
        case StrategyType.LIQUIDITY_SWEEP_EXHAUSTION:
            lines.append("<b>Concept:</b> Liquidity Sweep + Exhaustion (LSE)")
            lines.append("<b>Sweep:</b> Swing Break + Wick &gt;= 50%")
            lines.append("<b>Confirm:</b> Midpoint Penetration Close")
            lines.append("<b>Volume:</b> &gt;=1.3x | <b>RSI:</b> &lt;38 / &gt;62")
        case StrategyType.HIGH_CONFLUENCE_EXHAUSTION:
            lines.append("<b>Concept:</b> High Confluence Exhaustion")
            lines.append("<b>BB:</b> 20 (StdDev: 2.5)")
            lines.append("<b>RSI Extremes:</b> 20 / 80")
            lines.append("<b>Volume:</b> &gt;1.3x SMA20 | <b>ADX Max:</b> 35")
        case _:
            lines.append(f"<b>Fast EMA period:</b> {fast_period}")
            lines.append(f"<b>Slow EMA period:</b> {slow_period}")

    if strategy_type is not None:
        opt_interval = get_strategy_default_interval(strategy_type)
        sl_pct, tp_pct = get_strategy_default_exit_rates(strategy_type)
        lines.append(f"<b>Auto Timeframe:</b> <code>{opt_interval.value}</code>")
        lines.append(
            f"<b>Target RRR:</b> <code>1:2</code> "
            f"(SL {sl_pct * 100:.1f}% | TP {tp_pct * 100:.1f}%)"
        )

    return "\n".join(lines)


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
        format_price(last_price, symbol="USDT")
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


def get_risk_limits_message(
    *,
    limits: RuntimeRiskLimits,
    max_open_positions_ceiling: int,
    max_position_size_usdt_ceiling: Decimal,
    is_paused: bool,
) -> str:
    """Return formatted autonomous LIVE risk limits status and controls."""
    updated_str = limits.updated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    pause_status = (
        "🟢 <b>PAUSED (Bisa diubah)</b>"
        if is_paused
        else "🔴 <b>RUNNING (Jeda bot untuk mengubah)</b>"
    )
    return (
        "⚙️ <b>Runtime Risk Limits</b>\n\n"
        f"• <b>Status:</b> {pause_status}\n"
        f"• <b>Max Open Positions:</b> <b>{limits.max_open_positions}</b> "
        f"(Ceiling: {max_open_positions_ceiling})\n"
        f"• <b>Max Position Size:</b> <b>{limits.max_position_size_usdt} USDT</b> "
        f"(Ceiling: {max_position_size_usdt_ceiling} USDT)\n"
        f"• <b>Source:</b> <code>{limits.updated_by}</code>\n"
        f"• <b>Updated:</b> <code>{updated_str}</code>\n\n"
        "<i>Gunakan tombol di bawah atau perintah: "
        "<code>/setrisklimits &lt;pos&gt; &lt;size&gt;</code></i>"
    )


def get_tpsl_ratio_message(
    *,
    stop_loss_pct: Decimal,
    take_profit_pct: Decimal,
    is_paused: bool,
) -> str:
    """Return formatted TP/SL ratio status and tuning controls."""
    pause_status = (
        "🟢 <b>PAUSED (Bisa diubah)</b>"
        if is_paused
        else "🔴 <b>RUNNING (Jeda bot untuk mengubah)</b>"
    )
    sl_pct_display = stop_loss_pct * Decimal("100")
    tp_pct_display = take_profit_pct * Decimal("100")
    rr_ratio = (
        (tp_pct_display / sl_pct_display)
        if sl_pct_display > Decimal("0")
        else Decimal("0")
    )

    return (
        "🎯 <b>Konfigurasi TP / SL & Risk:Reward Ratio</b>\n\n"
        f"• <b>Status:</b> {pause_status}\n"
        f"• <b>Stop Loss (SL):</b> <b>{sl_pct_display:.2f}%</b>\n"
        f"• <b>Take Profit (TP):</b> <b>{tp_pct_display:.2f}%</b>\n"
        f"• <b>Risk : Reward Ratio:</b> <b>1 : {rr_ratio:.2f}</b>\n\n"
        "<i>Gunakan tombol di bawah untuk fine-tuning atau memilih preset RR "
        "(saat PAUSED).</i>"
    )
