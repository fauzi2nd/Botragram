"""Tests for Telegram performance card and enhanced trade completion message."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Update
from telegram.ext import ContextTypes

from botragram.constants.telegram import (
    DEFAULT_PARSE_MODE,
    MENU_PERFORMANCE,
)
from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    OrderSide,
    PositionSide,
)
from botragram.models import (
    ClosedPositionLifecycle,
    PendingClosedPositionLifecycle,
    Trade,
)
from botragram.services.live_trading_performance_service import (
    TradingPerformanceSnapshot,
)
from botragram.telegram.callbacks import handle_callback_query
from botragram.telegram.commands import menu_message_handler, performance_command
from botragram.telegram.context import (
    ALLOWED_CHAT_IDS_KEY,
    BOT_CONTEXT_KEY,
    BotContext,
)
from botragram.telegram.messages import (
    get_performance_card_message,
    get_trade_completed_message,
)
from botragram.telegram.query_service import (
    LiveMarketStreamService,
    TelegramQueryService,
)


def _make_dummy_trade(
    *,
    side: OrderSide,
    price: Decimal,
    quantity: Decimal,
    executed_at: datetime,
) -> Trade:
    return Trade(
        trade_id="t-1",
        order_id="o-1",
        symbol="BTCUSDT",
        side=side,
        price=price,
        quantity=quantity,
        quote_quantity=price * quantity,
        fee=Decimal("0.05"),
        fee_asset="USDT",
        executed_at=executed_at,
    )


def _make_dummy_lifecycle(
    *,
    net_pnl: Decimal,
    recorded_at: datetime,
    closed_at: datetime,
) -> ClosedPositionLifecycle:
    pending = PendingClosedPositionLifecycle(
        entry_client_order_id="entry-1",
        symbol="BTCUSDT",
        position_side=PositionSide.LONG,
        entry_order_id="eo-1",
        exit_client_order_id="exit-1",
        exit_order_id="exo-1",
        close_reason=ClosedPositionReason.TAKE_PROFIT,
        provenance=ClosedPositionProvenance.PROTECTION_ORDER,
        recorded_at=recorded_at,
    )
    return ClosedPositionLifecycle(
        ownership=pending,
        gross_realized_pnl=net_pnl + Decimal("0.10"),
        fee=Decimal("0.10"),
        fee_asset="USDT",
        net_pnl=net_pnl,
        closed_at=closed_at,
    )


def test_get_trade_completed_message_with_duration_and_roi() -> None:
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
    entry_time = now - timedelta(hours=1, minutes=23, seconds=45)

    entry_fill = _make_dummy_trade(
        side=OrderSide.BUY,
        price=Decimal("50000"),
        quantity=Decimal("0.01"),  # cost = 500 USDT
        executed_at=entry_time,
    )
    exit_fill = _make_dummy_trade(
        side=OrderSide.SELL,
        price=Decimal("55000"),
        quantity=Decimal("0.01"),
        executed_at=now,
    )
    lifecycle = _make_dummy_lifecycle(
        net_pnl=Decimal("49.90"),  # ~ +9.98% ROI
        recorded_at=entry_time,
        closed_at=now,
    )

    msg = get_trade_completed_message(
        lifecycle=lifecycle,
        entry_fills=(entry_fill,),
        exit_fills=(exit_fill,),
    )

    assert "🟢 <b>Trade Completed (WIN)</b>" in msg
    assert "<b>Duration:</b> 1h 23m 45s" in msg
    assert "(+9.98%)" in msg
    assert "<b>Net Realized PnL:</b> <b>+49.90 USDT</b>" in msg


def test_get_trade_completed_message_fallback_duration() -> None:
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
    recorded_at = now - timedelta(minutes=15, seconds=30)
    lifecycle = _make_dummy_lifecycle(
        net_pnl=Decimal("-10.00"),
        recorded_at=recorded_at,
        closed_at=now,
    )

    msg = get_trade_completed_message(lifecycle=lifecycle)

    assert "🔴 <b>Trade Completed (LOSS)</b>" in msg
    assert "<b>Duration:</b> 15m 30s" in msg
    assert "<b>Net Realized PnL:</b> <b>-10.00 USDT</b>" in msg


def test_get_performance_card_message() -> None:
    snapshot = TradingPerformanceSnapshot(
        closed_trade_count=10,
        win_count=7,
        loss_count=2,
        break_even_count=1,
        realized_pnl=Decimal("125.50"),
        win_rate_percent=Decimal("77.8"),
    )
    msg = get_performance_card_message(snapshot, mode="LIVE")

    assert "📊 <b>Trading Performance Card (LIVE)</b>" in msg
    assert "+125.50 USDT" in msg
    assert "77.8%" in msg
    assert "Total Closed Trades:</b> 10" in msg
    assert "Wins:</b> 7 🟢" in msg
    assert "Losses:</b> 2 🔴" in msg
    assert "Break-Even:</b> 1 ⚪" in msg


def test_get_performance_card_message_none() -> None:
    msg = get_performance_card_message(None, mode="LIVE")
    assert "Data performa belum tersedia" in msg


@pytest.mark.asyncio
async def test_telegram_query_service_performance() -> None:
    mock_perf_service = MagicMock()
    dummy_snapshot = TradingPerformanceSnapshot(
        closed_trade_count=5,
        win_count=4,
        loss_count=1,
        break_even_count=0,
        realized_pnl=Decimal("50.00"),
        win_rate_percent=Decimal("80.0"),
    )
    mock_perf_service.get_snapshot = AsyncMock(return_value=dummy_snapshot)

    qs = TelegramQueryService(
        symbol="BTCUSDT",
        market_service=MagicMock(),
        paper_trading_service=MagicMock(),
        position_repository=MagicMock(),
        trade_repository=MagicMock(),
        order_repository=MagicMock(),
        market_stream_service=MagicMock(spec=LiveMarketStreamService),
        live_trading_performance_service=mock_perf_service,
    )

    result = await qs.get_trading_performance()
    assert result == dummy_snapshot
    mock_perf_service.get_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_performance_command_authorized() -> None:
    snapshot = TradingPerformanceSnapshot(
        closed_trade_count=3,
        win_count=2,
        loss_count=1,
        break_even_count=0,
        realized_pnl=Decimal("30.00"),
        win_rate_percent=Decimal("66.7"),
    )
    mock_query = MagicMock()
    mock_query.get_trading_performance = AsyncMock(return_value=snapshot)

    bot_ctx = BotContext(
        trade_mode="LIVE",
        query_provider=mock_query,
    )

    update = MagicMock(spec=Update)
    message = MagicMock()
    message.reply_text = AsyncMock()
    update.message = message
    update.effective_chat = MagicMock(id=123)
    update.effective_user = MagicMock(id=123)

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot_data = {
        BOT_CONTEXT_KEY: bot_ctx,
        ALLOWED_CHAT_IDS_KEY: {123},
    }

    await performance_command(update, context)

    message.reply_text.assert_awaited_once()
    args, kwargs = message.reply_text.call_args
    assert "Trading Performance Card (LIVE)" in args[0]
    assert "+30.00 USDT" in args[0]
    assert kwargs.get("parse_mode") == DEFAULT_PARSE_MODE


@pytest.mark.asyncio
async def test_menu_message_handler_performance() -> None:
    snapshot = TradingPerformanceSnapshot(
        closed_trade_count=1,
        win_count=1,
        loss_count=0,
        break_even_count=0,
        realized_pnl=Decimal("10.00"),
        win_rate_percent=Decimal("100.0"),
    )
    mock_query = MagicMock()
    mock_query.get_trading_performance = AsyncMock(return_value=snapshot)

    bot_ctx = BotContext(
        trade_mode="LIVE",
        query_provider=mock_query,
    )

    update = MagicMock(spec=Update)
    message = MagicMock()
    message.text = MENU_PERFORMANCE
    message.reply_text = AsyncMock()
    update.message = message
    update.effective_chat = MagicMock(id=123)
    update.effective_user = MagicMock(id=123)

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.chat_data = {}
    context.bot_data = {
        BOT_CONTEXT_KEY: bot_ctx,
        ALLOWED_CHAT_IDS_KEY: {123},
    }

    await menu_message_handler(update, context)

    message.reply_text.assert_awaited_once()
    args, _ = message.reply_text.call_args
    assert "Trading Performance Card (LIVE)" in args[0]


@pytest.mark.asyncio
async def test_callback_cb_performance() -> None:
    snapshot = TradingPerformanceSnapshot(
        closed_trade_count=2,
        win_count=1,
        loss_count=1,
        break_even_count=0,
        realized_pnl=Decimal("5.00"),
        win_rate_percent=Decimal("50.0"),
    )
    mock_query = MagicMock()
    mock_query.get_trading_performance = AsyncMock(return_value=snapshot)

    bot_ctx = BotContext(
        trade_mode="LIVE",
        query_provider=mock_query,
    )

    query = MagicMock()
    query.data = "cb_performance"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_chat = MagicMock(id=123)
    update.effective_user = MagicMock(id=123)

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot_data = {
        BOT_CONTEXT_KEY: bot_ctx,
        ALLOWED_CHAT_IDS_KEY: {123},
    }

    await handle_callback_query(update, context)

    query.edit_message_text.assert_awaited_once()
    args, _ = query.edit_message_text.call_args
    assert "Trading Performance Card (LIVE)" in args[0]
    assert "+5.00 USDT" in args[0]
