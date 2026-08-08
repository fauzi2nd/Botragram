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
from botragram.constants.telegram import MENU_MARKET, MENU_MARKET_OVERVIEW
from botragram.enums import (
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.models import Order, Position, Trade
from botragram.telegram.context import BotContext
from botragram.telegram.keyboards import (
    get_activity_menu_keyboard,
    get_configuration_menu_keyboard,
    get_dashboard_menu_keyboard,
    get_exchange_keyboard,
    get_interval_keyboard,
    get_main_menu_keyboard,
    get_market_keyboard,
    get_strategy_keyboard,
    get_trading_menu_keyboard,
)
from botragram.telegram.messages import (
    get_exchange_message,
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
    get_welcome_message,
)

# =============================================================================
# Constants
# =============================================================================
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


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

    assert len(main_menu.keyboard) == 2
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
