"""
Botragram

Description:
    Unit and integration tests for Telegram futures leverage controls.

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
from dataclasses import dataclass
from datetime import UTC, datetime
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
from botragram.models import RuntimeRiskLimits
from botragram.telegram.callbacks import handle_callback_query
from botragram.telegram.context import (
    ALLOWED_CHAT_IDS_KEY,
    BOT_CONTEXT_KEY,
    BotContext,
)
from botragram.telegram.leverage_commands import (
    leverage_command,
    set_leverage_command,
)
from botragram.telegram.risk_limit_commands import set_risk_limits_command


# =============================================================================
# Helper Fixtures
# =============================================================================
def _create_mock_update_and_context(
    *,
    is_paused: bool = True,
    current_leverage: int = 5,
    user_id: int = 12345,
    chat_id: int = 12345,
    args: list[str] | None = None,
) -> tuple[MagicMock, MagicMock, TradingRuntimeControl, BotContext]:
    control = TradingRuntimeControl(leverage=current_leverage)
    if is_paused:
        control.pause()
    else:
        # satisfy startup requirements so resume doesn't fail
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
        leverage=current_leverage,
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
@pytest.mark.asyncio
async def test_leverage_command_displays_menu() -> None:
    """Verify /leverage command replies with leverage message and keyboard."""
    update, context, _, _ = _create_mock_update_and_context(
        current_leverage=5,
        is_paused=True,
    )

    await leverage_command(update, context)

    update.effective_message.reply_text.assert_called_once()
    call_args = update.effective_message.reply_text.call_args
    assert "5x" in call_args[0][0]
    assert "PAUSED" in call_args[0][0]
    assert call_args[1]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_set_leverage_command_success_when_paused() -> None:
    """Verify /setleverage 10 succeeds when the bot is paused."""
    update, context, control, bot_context = _create_mock_update_and_context(
        current_leverage=5,
        is_paused=True,
        args=["10"],
    )

    selected_leverages: list[int] = []
    control.bind_leverage_selector(selected_leverages.append)

    await set_leverage_command(update, context)

    assert control.leverage == 10
    assert bot_context.leverage == 10
    assert selected_leverages == [10]
    update.effective_message.reply_text.assert_called_once()
    assert "10x" in update.effective_message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_set_leverage_command_rejected_when_running() -> None:
    """Verify /setleverage is rejected with a warning when bot is running."""
    update, context, control, _ = _create_mock_update_and_context(
        current_leverage=5,
        is_paused=False,
        args=["10"],
    )

    await set_leverage_command(update, context)

    assert control.leverage == 5
    update.effective_message.reply_text.assert_called_once()
    assert "Jeda (pause)" in update.effective_message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_set_leverage_command_invalid_arguments() -> None:
    """Verify /setleverage handles invalid or out-of-range inputs safely."""
    # Missing args
    update, context, _, _ = _create_mock_update_and_context(args=[])
    await set_leverage_command(update, context)
    assert "Format penggunaan" in update.effective_message.reply_text.call_args[0][0]

    # Non-integer arg
    update, context, _, _ = _create_mock_update_and_context(args=["abc"])
    await set_leverage_command(update, context)
    assert "tidak valid" in update.effective_message.reply_text.call_args[0][0]

    # Out of range (e.g. 0 or 105)
    update, context, _, _ = _create_mock_update_and_context(args=["0"])
    await set_leverage_command(update, context)
    assert "tidak valid" in update.effective_message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_leverage_callback_fine_tuning_and_presets() -> None:
    """Verify callback interactions for increment, decrement, and presets."""
    control = TradingRuntimeControl(leverage=5)
    control.pause()
    bot_context = BotContext(
        is_running=True,
        leverage=5,
        runtime_control=control,
    )

    update = MagicMock()
    query = AsyncMock()
    query.data = "cb_leverage_inc_1"
    update.callback_query = query
    update.effective_user.id = 12345
    update.effective_chat.id = 12345

    context = MagicMock()
    context.bot_data = {
        BOT_CONTEXT_KEY: bot_context,
        ALLOWED_CHAT_IDS_KEY: [12345],
    }

    # +1x -> 6x
    await handle_callback_query(update, context)
    assert control.leverage == 6
    assert bot_context.leverage == 6
    query.edit_message_text.assert_called()

    # Preset 20x
    query.data = "cb_leverage_set_20"
    await handle_callback_query(update, context)
    assert control.leverage == 20
    assert bot_context.leverage == 20

    # -5x -> 15x
    query.data = "cb_leverage_dec_5"
    await handle_callback_query(update, context)
    assert control.leverage == 15
    assert bot_context.leverage == 15


@pytest.mark.asyncio
async def test_leverage_callback_rejected_when_running() -> None:
    """Verify modifying leverage via callback alerts user if bot is not paused."""
    control = TradingRuntimeControl(leverage=5)
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
        leverage=5,
        runtime_control=control,
    )

    update = MagicMock()
    query = AsyncMock()
    query.data = "cb_leverage_inc_1"
    update.callback_query = query
    update.effective_user.id = 12345
    update.effective_chat.id = 12345

    context = MagicMock()
    context.bot_data = {
        BOT_CONTEXT_KEY: bot_context,
        ALLOWED_CHAT_IDS_KEY: [12345],
    }

    await handle_callback_query(update, context)
    assert control.leverage == 5
    assert bot_context.leverage == 5
    query.answer.assert_called_with(
        "⚠️ Pause trading terlebih dahulu sebelum mengubah leverage!",
        show_alert=True,
    )


@dataclass(slots=True)
class _FakeRuntimeRiskLimitService:
    snapshot: RuntimeRiskLimits
    max_open_positions_ceiling: int = 10
    max_position_size_usdt_ceiling: Decimal = Decimal("100")

    def get_snapshot(self) -> RuntimeRiskLimits:
        return self.snapshot

    async def update(
        self,
        *,
        max_open_positions: int,
        max_position_size_usdt: Decimal,
        updated_by: str,
    ) -> RuntimeRiskLimits:
        self.snapshot = RuntimeRiskLimits(
            max_open_positions=max_open_positions,
            max_position_size_usdt=max_position_size_usdt,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
        )
        return self.snapshot


@pytest.mark.asyncio
async def test_risk_limits_leverage_tuning_callbacks() -> None:
    """Verify modifying leverage within risk limits menu updates state and message."""
    limits = RuntimeRiskLimits(
        max_open_positions=5,
        max_position_size_usdt=Decimal("50"),
        updated_at=datetime.now(UTC),
        updated_by="telegram:12345",
    )
    risk_service = _FakeRuntimeRiskLimitService(snapshot=limits)
    control = TradingRuntimeControl(leverage=5)
    control.pause()

    bot_context = BotContext(
        is_running=True,
        leverage=5,
        leverage_ceiling=50,
        runtime_control=control,
        runtime_risk_limit_service=risk_service,  # type: ignore[arg-type]
    )

    update = MagicMock()
    query = AsyncMock()
    update.callback_query = query
    update.effective_user.id = 12345
    update.effective_chat.id = 12345

    context = MagicMock()
    context.bot_data = {
        BOT_CONTEXT_KEY: bot_context,
        ALLOWED_CHAT_IDS_KEY: [12345],
    }

    # +5x Lev -> 10x
    query.data = "cb_risk_lev_inc"
    await handle_callback_query(update, context)
    assert control.leverage == 10
    assert bot_context.leverage == 10
    call_args = query.edit_message_text.call_args
    assert "10x" in call_args[0][0]
    assert "Ceiling: 50x" in call_args[0][0]

    # -5x Lev -> 5x
    query.data = "cb_risk_lev_dec"
    await handle_callback_query(update, context)
    assert control.leverage == 5
    assert bot_context.leverage == 5

    # Preset 25x -> 25x
    query.data = "cb_risk_set_lev_25"
    await handle_callback_query(update, context)
    assert control.leverage == 25
    assert bot_context.leverage == 25


@pytest.mark.asyncio
async def test_risk_limits_leverage_callback_rejected_when_running() -> None:
    """Verify cb_risk_lev_inc is rejected with alert when bot is running."""
    limits = RuntimeRiskLimits(
        max_open_positions=5,
        max_position_size_usdt=Decimal("50"),
        updated_at=datetime.now(UTC),
        updated_by="telegram:12345",
    )
    risk_service = _FakeRuntimeRiskLimitService(snapshot=limits)
    control = TradingRuntimeControl(leverage=5)
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
        leverage=5,
        leverage_ceiling=50,
        runtime_control=control,
        runtime_risk_limit_service=risk_service,  # type: ignore[arg-type]
    )

    update = MagicMock()
    query = AsyncMock()
    query.data = "cb_risk_lev_inc"
    update.callback_query = query
    update.effective_user.id = 12345
    update.effective_chat.id = 12345

    context = MagicMock()
    context.bot_data = {
        BOT_CONTEXT_KEY: bot_context,
        ALLOWED_CHAT_IDS_KEY: [12345],
    }

    await handle_callback_query(update, context)
    assert control.leverage == 5
    assert bot_context.leverage == 5
    query.answer.assert_called_with(
        "⚠️ Pause trading terlebih dahulu sebelum mengubah risk limits!",
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_set_risk_limits_command_with_leverage() -> None:
    """Verify /setrisklimits <pos> <size> <leverage> updates leverage and limits."""
    limits = RuntimeRiskLimits(
        max_open_positions=5,
        max_position_size_usdt=Decimal("50"),
        updated_at=datetime.now(UTC),
        updated_by="telegram:12345",
    )
    risk_service = _FakeRuntimeRiskLimitService(snapshot=limits)
    control = TradingRuntimeControl(leverage=5)
    control.pause()

    bot_context = BotContext(
        is_running=True,
        leverage=5,
        leverage_ceiling=50,
        runtime_control=control,
        runtime_risk_limit_service=risk_service,  # type: ignore[arg-type]
    )

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 12345
    message = AsyncMock()
    update.effective_message = message

    context = MagicMock()
    context.bot_data = {
        BOT_CONTEXT_KEY: bot_context,
        ALLOWED_CHAT_IDS_KEY: [12345],
    }
    context.args = ["3", "20", "15"]

    await set_risk_limits_command(update, context)
    assert control.leverage == 15
    assert bot_context.leverage == 15
    assert risk_service.snapshot.max_open_positions == 3
    assert risk_service.snapshot.max_position_size_usdt == Decimal("20")

    message.reply_text.assert_called_once()
    reply_content = message.reply_text.call_args[0][0]
    assert "15x" in reply_content
