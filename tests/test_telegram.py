"""
Botragram

Description:
    Telegram context, message, and keyboard adapter tests.

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
from datetime import datetime, timezone
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import (
    MENU_CONFIGURATION,
    MENU_MARKET,
    MENU_MARKET_OVERVIEW,
    MENU_PAUSE,
    MENU_RESUME,
    MENU_RISK_LIMITS,
    MENU_START,
    MENU_TRADING,
    MENU_TRADING_MODE,
)
from botragram.enums import (
    AuthorizationStatus,
    ExecutionPolicy,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
)
from botragram.models import ExecutionAuthorization, Order, Position, Signal, Trade
from botragram.telegram.bot import get_bot_commands
from botragram.telegram.context import BotContext
from botragram.telegram.keyboards import (
    get_activity_menu_keyboard,
    get_configuration_menu_keyboard,
    get_dashboard_menu_keyboard,
    get_exchange_keyboard,
    get_execution_authorization_keyboard,
    get_execution_policy_keyboard,
    get_interval_keyboard,
    get_main_menu_keyboard,
    get_market_keyboard,
    get_strategy_keyboard,
    get_tpsl_ratio_keyboard,
    get_trading_menu_keyboard,
)
from botragram.telegram.messages import (
    get_exchange_message,
    get_execution_authorization_message,
    get_interval_message,
    get_market_message,
    get_orders_message,
    get_paper_entry_message,
    get_paper_exit_message,
    get_positions_message,
    get_settings_message,
    get_startup_configuration_message,
    get_status_message,
    get_strategy_message,
    get_stream_message,
    get_tpsl_ratio_message,
    get_welcome_message,
)

# =============================================================================
# Constants
# =============================================================================
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# =============================================================================
# Command Registry Tests
# =============================================================================
def test_public_bot_command_registry_is_unique_and_complete() -> None:
    """Expose every operator command exactly once to Telegram clients."""
    commands = get_bot_commands()
    names = tuple(command.command for command in commands)

    assert len(names) == len(set(names))
    assert {
        "exitstatus",
        "closeposition",
        "closeall",
        "closeandswitch",
        "confirmexit",
        "cancelexit",
    } <= set(names)


# =============================================================================
# Mode-aware Menu Tests
# =============================================================================
def test_autonomous_live_home_hides_single_symbol_controls() -> None:
    """Expose monitoring/risk/runtime controls without manual symbol setup."""
    running = get_main_menu_keyboard(
        execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
        is_paused=False,
    )
    paused = get_main_menu_keyboard(
        execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
        is_paused=True,
    )
    running_labels = {button.text for row in running.keyboard for button in row}
    paused_labels = {button.text for row in paused.keyboard for button in row}

    assert MENU_CONFIGURATION not in running_labels
    assert MENU_TRADING not in running_labels
    assert MENU_RISK_LIMITS in running_labels
    assert MENU_TRADING_MODE in running_labels
    assert MENU_PAUSE in running_labels
    assert MENU_RESUME in paused_labels


def test_single_symbol_home_keeps_setup_and_adds_mode_switch() -> None:
    """Keep manual configuration available only in single-symbol workflow."""
    keyboard = get_main_menu_keyboard(
        execution_policy=ExecutionPolicy.SINGLE_SYMBOL,
        is_paused=True,
    )
    labels = {button.text for row in keyboard.keyboard for button in row}

    assert MENU_CONFIGURATION in labels
    assert MENU_TRADING in labels
    assert MENU_TRADING_MODE in labels
    assert MENU_RISK_LIMITS not in labels


def test_execution_policy_keyboard_shows_only_allowed_targets() -> None:
    """Never render a workflow outside the boot capability envelope."""
    markup = get_execution_policy_keyboard(
        current_policy=ExecutionPolicy.SINGLE_SYMBOL,
        available_policies=(
            ExecutionPolicy.SINGLE_SYMBOL,
            ExecutionPolicy.AUTONOMOUS_LIVE,
        ),
    )
    labels = {button.text for row in markup.inline_keyboard for button in row}

    assert any("Single Symbol" in label for label in labels)
    assert any("Auto Discovery" in label for label in labels)
    assert not any("Human Confirmed" in label for label in labels)


# =============================================================================
# Message Tests
# =============================================================================
def test_welcome_message_contains_identity_and_security_notice() -> None:
    """Verify welcome content identifies Botragram and protects credentials."""
    message = get_welcome_message()

    assert "Botragram" in message
    assert "Keamanan" in message
    assert "API key" in message


def test_status_and_settings_messages_escape_external_text() -> None:
    """Verify Telegram HTML cannot be injected through displayed settings."""
    status = get_status_message(
        is_running=True,
        trade_mode="<LIVE>",
        symbol="BTC&USDT",
        last_price=Decimal("100.5"),
    )
    settings = get_settings_message(
        exchange_type="<BINANCE>",
        strategy_name="EMA&RSI",
        trade_mode="PAPER",
    )

    assert "🟢 RUNNING" in status
    assert "&lt;LIVE&gt;" in status
    assert "BTC&amp;USDT" in status
    assert "100.50 USDT" in status
    assert "&lt;BINANCE&gt;" in settings
    assert "EMA&amp;RSI" in settings


def test_configuration_messages_hide_unconfirmed_runtime_defaults() -> None:
    """Do not present environment defaults as Telegram selections."""
    exchange = get_exchange_message("BINANCE", MarketType.FUTURES)
    market = get_market_message("BTCUSDT", Decimal("65000"))
    strategy = get_strategy_message("ema_cross", 9, 21)
    interval = get_interval_message("15m")

    assert "Exchange:</b> Belum dipilih" in exchange
    assert "Product:</b> Belum dipilih" in exchange
    assert "Symbol:</b> Belum dipilih" in market
    assert "Last Price:</b> WAITING" in market
    assert "Strategy:</b> Belum dipilih" in strategy
    assert "Interval:</b> Belum dipilih" in interval


def test_configuration_messages_show_confirmed_runtime_selections() -> None:
    """Show runtime defaults only after explicit Telegram confirmation."""
    exchange = get_exchange_message(
        "BINANCE",
        MarketType.FUTURES,
        exchange_confirmed=True,
        market_type_confirmed=True,
    )
    market = get_market_message(
        "BTCUSDT",
        Decimal("65000"),
        confirmed=True,
    )
    strategy = get_strategy_message("ema_cross", 9, 21, confirmed=True)
    interval = get_interval_message("15m", confirmed=True)

    assert "Exchange:</b> 🟠 <b>Binance</b>" in exchange
    assert "Product:</b> Futures" in exchange
    assert "Symbol:</b> BTCUSDT" in market
    assert "65000.00 USDT" in market
    assert "Strategy:</b> ema_cross" in strategy
    assert "Interval:</b> 15m" in interval


def test_market_and_stream_messages_never_present_zero_as_a_price() -> None:
    """Render unavailable prices as waiting and validated ticks as currency."""
    market_waiting = get_market_message("BTCUSDT", Decimal("0"))
    stream_live = get_stream_message(
        transport_connected=True,
        subscription_active=True,
        first_tick_received=True,
        last_price=Decimal("65000.5"),
    )

    assert "Last Price:</b> WAITING" in market_waiting
    assert "First Tick:</b> RECEIVED" in stream_live
    assert "65000.50 USDT" in stream_live


def test_startup_checklist_hides_each_missing_selection() -> None:
    """Render incomplete startup configuration without leaking defaults."""
    message = get_startup_configuration_message(
        exchange="BINANCE",
        market_type="FUTURES",
        symbol="BTCUSDT",
        interval="15m",
        strategy="ema_cross",
        missing_requirements=(
            "exchange",
            "market type",
            "symbol",
            "interval",
            "strategy",
            "stream subscription",
            "first stream tick",
        ),
    )

    assert message.count("BELUM DIPILIH") == 5
    assert "BINANCE" not in message
    assert "FUTURES" not in message
    assert "BTCUSDT" not in message
    assert "15m" not in message
    assert "ema_cross" not in message


def test_positions_message_uses_current_domain_model() -> None:
    """Verify positions are rendered from immutable Position models."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("2"),
        entry_price=Decimal("100"),
        current_price=Decimal("110"),
        unrealized_pnl=Decimal("20"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )

    message = get_positions_message((position,))

    assert "BTCUSDT" in message
    assert "LONG" in message
    assert "Qty=2" in message
    assert "PnL=20.00 USDT" in message
    assert "Tidak ada posisi" in get_positions_message(())


def test_orders_message_uses_current_domain_model() -> None:
    """Verify orders are rendered from immutable Order models."""
    order = Order(
        order_id="1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        status=OrderStatus.NEW,
        quantity=Decimal("1.5"),
        executed_quantity=Decimal("0"),
        price=Decimal("100"),
        created_at=_NOW,
        updated_at=_NOW,
    )

    message = get_orders_message((order,))

    assert "BTCUSDT" in message
    assert "BUY limit" in message
    assert "qty=1.5" in message
    assert "Tidak ada order" in get_orders_message(())


def test_paper_notifications_include_portfolio_results_and_escape_reason() -> None:
    """Render entry and exit details without allowing Telegram HTML injection."""
    order = Order(
        order_id="paper-1",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        quantity=Decimal("2"),
        executed_quantity=Decimal("2"),
        price=Decimal("110"),
        created_at=_NOW,
        updated_at=_NOW,
    )
    trade = Trade(
        trade_id="paper-trade-1",
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        price=Decimal("110"),
        quantity=Decimal("2"),
        quote_quantity=Decimal("220"),
        fee=Decimal("0.22"),
        fee_asset="USDT",
        executed_at=_NOW,
        realized_pnl=Decimal("19.58"),
    )
    position = Position(
        symbol=order.symbol,
        side=PositionSide.LONG,
        quantity=order.quantity,
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("98"),
        take_profit=Decimal("104"),
    )

    entry_message = get_paper_entry_message(
        order=order,
        trade=trade,
        position=position,
        available_balance=Decimal("9000"),
    )
    exit_message = get_paper_exit_message(
        order=order,
        trade=trade,
        available_balance=Decimal("10019.58"),
        reason="Take profit <triggered>",
    )

    assert "Stop Loss" in entry_message
    assert "9000.00 USDT" in entry_message
    assert "Realized PnL" in exit_message
    assert "19.58 USDT" in exit_message
    assert "&lt;triggered&gt;" in exit_message


def test_execution_authorization_message_and_keyboard_are_paper_safe() -> None:
    """Render immutable opportunity details and opaque callback identifiers only."""
    authorization = ExecutionAuthorization(
        authorization_id="12345678123456781234567812345678",
        signal=Signal(
            symbol="BTC&lt;USDT",
            signal_type=SignalType.SELL,
            price=Decimal("100"),
            confidence=Decimal("0.875"),
            strategy_name="strategy<script>",
            generated_at=_NOW,
            reason="reason & <note>",
        ),
        status=AuthorizationStatus.PENDING,
        created_at=_NOW,
        expires_at=_NOW.replace(minute=5),
    )

    message = get_execution_authorization_message(authorization)
    keyboard = get_execution_authorization_keyboard(authorization.authorization_id)
    callbacks = {
        button.callback_data for row in keyboard.inline_keyboard for button in row
    }

    assert "PAPER" in message
    assert "SHORT" in message
    assert "87.50%" in message
    assert "BTC&amp;lt;USDT" in message
    assert "strategy&lt;script&gt;" in message
    assert "reason &amp; &lt;note&gt;" in message
    assert authorization.authorization_id not in message
    assert callbacks == {
        f"cb_opportunity_approve_{authorization.authorization_id}",
        f"cb_opportunity_reject_{authorization.authorization_id}",
    }
    assert all(
        isinstance(callback, str) and len(callback) <= 64 for callback in callbacks
    )


# =============================================================================
# Context and Keyboard Tests
# =============================================================================
def test_bot_context_has_safe_binance_paper_defaults() -> None:
    """Verify Telegram state defaults do not imply live trading."""
    context = BotContext()

    assert not context.is_running
    assert context.trade_mode == "PAPER"
    assert context.exchange_type == "BINANCE"
    assert context.market_type is MarketType.SPOT
    assert context.positions == ()


def test_main_menu_and_exchange_keyboard_have_stable_actions() -> None:
    """Verify Telegram keyboards expose menu and exchange callback actions."""
    main_menu = get_main_menu_keyboard()
    exchange_menu = get_exchange_keyboard("BINANCE", MarketType.FUTURES)

    submenu_keyboards = (
        get_dashboard_menu_keyboard(),
        get_trading_menu_keyboard(),
        get_configuration_menu_keyboard(),
        get_activity_menu_keyboard(),
    )
    dashboard_menu = get_dashboard_menu_keyboard()
    configuration_menu = get_configuration_menu_keyboard()

    assert len(main_menu.keyboard) == 3
    assert all(len(keyboard.keyboard) <= 4 for keyboard in submenu_keyboards)
    assert all(
        any(button.text == "🏠 Home" for row in keyboard.keyboard for button in row)
        for keyboard in submenu_keyboards
    )
    dashboard_labels = {
        button.text for row in dashboard_menu.keyboard for button in row
    }
    configuration_labels = {
        button.text for row in configuration_menu.keyboard for button in row
    }
    assert MENU_MARKET_OVERVIEW in dashboard_labels
    assert MENU_MARKET not in dashboard_labels
    assert MENU_MARKET in configuration_labels
    assert MENU_MARKET_OVERVIEW not in configuration_labels
    callback_data = {
        button.callback_data for row in exchange_menu.inline_keyboard for button in row
    }
    assert callback_data == {
        "cb_back_main",
        "cb_exchange_binance",
        "cb_product_spot",
        "cb_product_futures",
    }
    futures_button = next(
        button
        for row in exchange_menu.inline_keyboard
        for button in row
        if button.callback_data == "cb_product_futures"
    )
    assert not futures_button.text.startswith("✅")

    unconfirmed_keyboards = (
        exchange_menu,
        get_market_keyboard("BTCUSDT", ("BTCUSDT", "ETHUSDT")),
        get_strategy_keyboard("ema_cross"),
        get_interval_keyboard("15m"),
    )
    assert all(
        not button.text.startswith("✅")
        for keyboard in unconfirmed_keyboards
        for row in keyboard.inline_keyboard
        for button in row
    )

    confirmed_exchange = get_exchange_keyboard(
        "BINANCE",
        MarketType.FUTURES,
        exchange_confirmed=True,
        market_type_confirmed=True,
    )
    confirmed_labels = {
        button.text for row in confirmed_exchange.inline_keyboard for button in row
    }
    assert "✅ 🟠 BINANCE" in confirmed_labels
    assert "✅ Futures" in confirmed_labels


def test_market_keyboard_paginates_dynamic_exchange_symbols() -> None:
    """Keep a large exchange market catalog inside a compact inline page."""
    symbols = tuple(f"COIN{index:02d}USDT" for index in range(23))
    keyboard = get_market_keyboard(
        "COIN12USDT",
        symbols,
    )
    callbacks = {
        button.callback_data for row in keyboard.inline_keyboard for button in row
    }

    assert len(keyboard.inline_keyboard) == 8
    assert "cb_market_coin12usdt" in callbacks
    assert "cb_market_page_0" in callbacks
    assert "cb_market_page_2" in callbacks
    assert "cb_market_noop" in callbacks
    assert "cb_market_search" in callbacks


def test_tpsl_ratio_keyboard_and_message() -> None:
    """Format TP/SL ratio controls and verify callback buttons."""
    message = get_tpsl_ratio_message(
        stop_loss_pct=Decimal("0.01"),
        take_profit_pct=Decimal("0.02"),
        is_paused=True,
    )
    assert "Konfigurasi TP / SL" in message
    assert "1.00%" in message
    assert "2.00%" in message
    assert "1 : 2.00" in message
    assert "PAUSED" in message

    keyboard = get_tpsl_ratio_keyboard(
        stop_loss_pct=Decimal("0.01"),
        take_profit_pct=Decimal("0.02"),
    )
    callbacks = {
        button.callback_data for row in keyboard.inline_keyboard for button in row
    }
    assert {
        "cb_tpsl_sl_dec",
        "cb_tpsl_sl_inc",
        "cb_tpsl_tp_dec",
        "cb_tpsl_tp_inc",
        "cb_tpsl_rr_1.5",
        "cb_tpsl_rr_2.0",
        "cb_tpsl_rr_3.0",
        "cb_tpsl_menu",
        "cb_status",
    } <= callbacks


def test_new_strategy_messages_and_keyboard() -> None:
    """Verify RSI BB scalping and VWAP breakout in messages and keyboard."""
    rsi_msg = get_strategy_message("rsi_bb_scalping", confirmed=True)
    assert "RSI period" in rsi_msg
    assert "BB period" in rsi_msg

    vwap_msg = get_strategy_message("vwap_breakout", confirmed=True)
    assert "VWAP" in vwap_msg
    assert "ATR period" in vwap_msg

    keyboard = get_strategy_keyboard("rsi_bb_scalping", confirmed=True)
    callbacks = {
        button.callback_data for row in keyboard.inline_keyboard for button in row
    }
    assert "cb_strategy_rsi_bb_scalping" in callbacks
    assert "cb_strategy_vwap_breakout" in callbacks


def test_trading_menu_keyboard_sync_with_pause_state() -> None:
    """Verify trading submenu action synchronizes with runtime pause state."""
    paused_keyboard = get_trading_menu_keyboard(is_paused=True)
    paused_labels = {button.text for row in paused_keyboard.keyboard for button in row}
    assert MENU_START in paused_labels
    assert MENU_PAUSE not in paused_labels

    running_keyboard = get_trading_menu_keyboard(is_paused=False)
    running_labels = {
        button.text for row in running_keyboard.keyboard for button in row
    }
    assert MENU_PAUSE in running_labels
    assert MENU_START not in running_labels
