"""
Botragram

Description:
    Unit tests for Telegram Trailing Stop menu, callbacks, and commands.

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
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.runtime_control import TradingRuntimeControl
from botragram.telegram.callbacks import handle_callback_query
from botragram.telegram.context import (
    ALLOWED_CHAT_IDS_KEY,
    BOT_CONTEXT_KEY,
    BotContext,
)
from botragram.telegram.keyboards import (
    get_risk_limits_keyboard,
    get_trailing_stop_keyboard,
)
from botragram.telegram.messages import get_trailing_stop_message
from botragram.telegram.trailing_stop_commands import (
    set_trailing_stop_command,
    trailing_stop_command,
)


# =============================================================================
# Helper Fixture
# =============================================================================
def _create_mock_context(
    *,
    is_paused: bool = True,
    trailing_stop_enabled: bool = True,
    trigger_pct: Decimal = Decimal("0.015"),
    distance_pct: Decimal = Decimal("0.008"),
    user_id: int = 12345,
    chat_id: int = 12345,
    args: list[str] | None = None,
) -> tuple[MagicMock, MagicMock, TradingRuntimeControl, BotContext]:
    control = TradingRuntimeControl(
        trailing_stop_enabled=trailing_stop_enabled,
        trailing_stop_trigger_pct=trigger_pct,
        trailing_stop_distance_pct=distance_pct,
    )
    if is_paused:
        control.pause()
    else:
        control.confirm_exchange(control.exchange_type)
        control.confirm_market_type(control.market_type)
        control.select_symbol(control.symbol)
        control.select_interval(control.interval)
        control.select_strategy(control.strategy_type)
        control.set_position_protection_ready(True)
        control.set_stream_enabled(True)
        control.record_stream_tick(price=Decimal("100"))
        control.resume()

    bot_context = BotContext(
        is_running=True,
        trailing_stop_enabled=trailing_stop_enabled,
        trailing_stop_trigger_pct=trigger_pct,
        trailing_stop_distance_pct=distance_pct,
        runtime_control=control,
    )

    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    message = AsyncMock()
    update.effective_message = message
    update.message = message

    context = MagicMock()
    context.bot_data = {
        BOT_CONTEXT_KEY: bot_context,
        ALLOWED_CHAT_IDS_KEY: [chat_id],
    }
    context.args = args or []
    return update, context, control, bot_context


# =============================================================================
# Tests
# =============================================================================
def test_trailing_stop_keyboard_layout() -> None:
    """Verify trailing stop keyboard contains toggle, presets, and nav buttons."""
    keyboard = get_trailing_stop_keyboard(
        enabled=True,
        trigger_pct=Decimal("0.015"),
        distance_pct=Decimal("0.008"),
    )
    assert len(keyboard.inline_keyboard) == 4
    # Row 0: Toggle
    assert "ACTIVE" in keyboard.inline_keyboard[0][0].text
    assert keyboard.inline_keyboard[0][0].callback_data == "cb_tstop_toggle"

    # Row 1: Trigger presets
    triggers = [btn.callback_data for btn in keyboard.inline_keyboard[1]]
    assert "cb_tstop_trig_0.015" in triggers
    assert "cb_tstop_trig_0.020" in triggers

    # Row 2: Distance presets
    distances = [btn.callback_data for btn in keyboard.inline_keyboard[2]]
    assert "cb_tstop_dist_0.008" in distances
    assert "cb_tstop_dist_0.010" in distances

    # Row 3: Nav
    nav_callbacks = [btn.callback_data for btn in keyboard.inline_keyboard[3]]
    assert "cb_trailing_stop" in nav_callbacks
    assert "cb_risk_limits" in nav_callbacks
    assert "cb_status" in nav_callbacks


def test_risk_limits_keyboard_has_trailing_stop_button() -> None:
    """Verify Risk Limits keyboard exposes trailing stop shortcut."""
    kb = get_risk_limits_keyboard(
        current_positions=1,
        current_size_usdt=Decimal("50"),
        max_open_positions_ceiling=5,
        max_position_size_usdt_ceiling=Decimal("200"),
    )
    all_callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "cb_trailing_stop" in all_callbacks


def test_trailing_stop_message_formatting() -> None:
    """Verify message shows status, trigger, and distance percentages."""
    msg = get_trailing_stop_message(
        enabled=True,
        trigger_pct=Decimal("0.02"),
        distance_pct=Decimal("0.01"),
        is_paused=True,
    )
    assert "ACTIVE" in msg
    assert "+2.00%" in msg
    assert "1.00%" in msg
    assert "PAUSED" in msg

    msg_disabled = get_trailing_stop_message(
        enabled=False,
        trigger_pct=Decimal("0.015"),
        distance_pct=Decimal("0.008"),
        is_paused=False,
    )
    assert "DISABLED" in msg_disabled
    assert "RUNNING" in msg_disabled


@pytest.mark.asyncio
async def test_trailing_stop_callback_toggle() -> None:
    """Verify toggle callback toggles state when paused."""
    update, context, control, bot_context = _create_mock_context(
        is_paused=True,
        trailing_stop_enabled=True,
    )
    query = AsyncMock()
    query.data = "cb_tstop_toggle"
    update.callback_query = query

    await handle_callback_query(update, context)

    assert control.trailing_stop_enabled is False
    assert bot_context.trailing_stop_enabled is False
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_trailing_stop_callback_rejects_when_running() -> None:
    """Verify trailing stop changes are rejected when bot is active/running."""
    update, context, control, _ = _create_mock_context(
        is_paused=False,
        trailing_stop_enabled=True,
    )
    query = AsyncMock()
    query.data = "cb_tstop_toggle"
    update.callback_query = query

    await handle_callback_query(update, context)

    # State unchanged
    assert control.trailing_stop_enabled is True
    assert any(
        "Pause trading" in str(call.args) for call in query.answer.await_args_list
    )


@pytest.mark.asyncio
async def test_trailing_stop_callback_tune_trigger_and_distance() -> None:
    """Verify tuning trigger and distance via callback updates control."""
    update, context, control, bot_context = _create_mock_context(
        is_paused=True,
        trailing_stop_enabled=True,
        trigger_pct=Decimal("0.015"),
        distance_pct=Decimal("0.008"),
    )
    query = AsyncMock()
    query.data = "cb_tstop_trig_0.025"
    update.callback_query = query

    await handle_callback_query(update, context)

    assert control.trailing_stop_trigger_pct == Decimal("0.025")
    assert bot_context.trailing_stop_trigger_pct == Decimal("0.025")

    # Now tune distance
    query.reset_mock()
    query.data = "cb_tstop_dist_0.012"
    await handle_callback_query(update, context)

    assert control.trailing_stop_distance_pct == Decimal("0.012")
    assert bot_context.trailing_stop_distance_pct == Decimal("0.012")


@pytest.mark.asyncio
async def test_trailing_stop_commands() -> None:
    """Verify /trailingstop and /settrail command behavior."""
    update, context, control, bot_context = _create_mock_context(
        is_paused=True,
        trailing_stop_enabled=True,
    )

    # Test /trailingstop
    await trailing_stop_command(update, context)
    update.effective_message.reply_text.assert_awaited_once()

    # Test /settrail on 2.0 1.0
    update.effective_message.reset_mock()
    context.args = ["on", "2.0", "1.0"]
    await set_trailing_stop_command(update, context)

    assert control.trailing_stop_enabled is True
    assert control.trailing_stop_trigger_pct == Decimal("0.02")
    assert control.trailing_stop_distance_pct == Decimal("0.01")
    assert "berhasil diperbarui" in update.effective_message.reply_text.call_args[0][0]

    # Test /settrail off
    update.effective_message.reset_mock()
    context.args = ["off"]
    await set_trailing_stop_command(update, context)

    assert control.trailing_stop_enabled is False
    assert bot_context.trailing_stop_enabled is False
