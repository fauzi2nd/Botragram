"""
Botragram

Description:
    Unit tests for Telegram bot message formatting and keyboards.

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
from botragram.telegram.keyboards import get_main_menu_keyboard
from botragram.telegram.messages import (
    get_positions_message,
    get_settings_message,
    get_status_message,
    get_welcome_message,
)


def test_telegram_messages() -> None:
    """Test Telegram message templates."""
    welcome = get_welcome_message()
    assert "Botragram" in welcome

    status = get_status_message(
        is_running=True,
        trade_mode="PAPER",
        symbol="BTCUSDT",
        last_price=Decimal("50000"),
    )
    assert "RUNNING" in status

    positions = get_positions_message([])
    assert "No active" in positions

    settings = get_settings_message(
        exchange_type="BYBIT",
        strategy_name="EMA_CROSS",
        trade_mode="PAPER",
    )
    assert "BYBIT" in settings


def test_telegram_keyboards() -> None:
    """Test Telegram persistent reply menu keyboard."""
    kb = get_main_menu_keyboard()
    assert len(kb.keyboard) == 3
    assert kb.is_persistent is True
