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
from botragram.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.models import Order, Position
from botragram.telegram.context import BotContext
from botragram.telegram.keyboards import (
    get_exchange_keyboard,
    get_main_menu_keyboard,
)
from botragram.telegram.messages import (
    get_orders_message,
    get_positions_message,
    get_settings_message,
    get_status_message,
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
    assert "long" in message
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


# =============================================================================
# Context and Keyboard Tests
# =============================================================================
def test_bot_context_has_safe_binance_paper_defaults() -> None:
    """Verify Telegram state defaults do not imply live trading."""
    context = BotContext()

    assert not context.is_running
    assert context.trade_mode == "PAPER"
    assert context.exchange_type == "BINANCE"
    assert context.positions == ()


def test_main_menu_and_exchange_keyboard_have_stable_actions() -> None:
    """Verify Telegram keyboards expose menu and exchange callback actions."""
    main_menu = get_main_menu_keyboard()
    exchange_menu = get_exchange_keyboard("BINANCE")

    assert len(main_menu.keyboard) == 7
    callback_data = {
        button.callback_data for row in exchange_menu.inline_keyboard for button in row
    }
    assert callback_data == {
        "cb_back_main",
        "cb_exchange_binance",
        "cb_exchange_bitget",
        "cb_exchange_bybit",
        "cb_exchange_okx",
    }
