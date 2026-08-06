"""Dynamic Telegram command and access-control tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast

from telegram import Update
from telegram.ext import ContextTypes

from botragram.app import TradingRuntimeControl
from botragram.enums import OrderSide, OrderStatus, OrderType, PositionSide
from botragram.models import Order, Position, Trade
from botragram.telegram.access import is_chat_allowed
from botragram.telegram.commands import (
    balance_command,
    history_command,
    orders_command,
    pause_bot_command,
    positions_command,
    start_bot_command,
    status_command,
)
from botragram.telegram.context import (
    ALLOWED_CHAT_IDS_KEY,
    BOT_CONTEXT_KEY,
    BotContext,
)

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_ALLOWED_CHAT_ID = 12345


@dataclass(slots=True)
class FakeMessage:
    """Capture Telegram replies emitted by command handlers."""

    text: str = ""
    replies: list[str] = field(default_factory=list[str])

    async def reply_text(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: object | None = None,
    ) -> None:
        """Capture one reply while accepting Telegram formatting arguments."""
        del parse_mode, reply_markup
        self.replies.append(text)


@dataclass(slots=True, frozen=True)
class FakeChat:
    """Minimal effective-chat representation."""

    id: int


@dataclass(slots=True)
class FakeUpdate:
    """Minimal update shape consumed by command handlers."""

    message: FakeMessage
    effective_chat: FakeChat


@dataclass(slots=True)
class FakeContext:
    """Minimal callback context with shared bot data."""

    bot_data: dict[str, object]


@dataclass(slots=True, kw_only=True)
class FakeQueryProvider:
    """Return deterministic live paper portfolio data."""

    positions: tuple[Position, ...]
    trades: tuple[Trade, ...]
    orders: tuple[Order, ...]
    balance: Decimal
    last_price: Decimal

    async def get_positions(self) -> Sequence[Position]:
        """Return active positions."""
        return self.positions

    async def get_available_balance(self) -> Decimal:
        """Return current paper balance."""
        return self.balance

    async def get_latest_trades(self, *, limit: int) -> Sequence[Trade]:
        """Return recent fills within the requested limit."""
        return self.trades[-limit:]

    async def get_latest_orders(self, *, limit: int) -> Sequence[Order]:
        """Return recent persisted orders within the requested limit."""
        return self.orders[-limit:]

    async def get_last_price(self) -> Decimal:
        """Return current market price."""
        return self.last_price


def _create_position() -> Position:
    """Create one active paper position."""
    return Position(
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


def _create_trade() -> Trade:
    """Create one closed paper fill."""
    return Trade(
        trade_id="paper-trade",
        order_id="paper-order",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        price=Decimal("110"),
        quantity=Decimal("2"),
        quote_quantity=Decimal("220"),
        fee=Decimal("0.22"),
        fee_asset="USDT",
        executed_at=_NOW,
        realized_pnl=Decimal("19.58"),
    )


def _create_order() -> Order:
    """Create one filled paper order."""
    return Order(
        order_id="paper-order",
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


def test_dynamic_commands_read_current_paper_portfolio() -> None:
    """Verify core commands render live query-provider values."""
    asyncio.run(_run_dynamic_command_test())


async def _run_dynamic_command_test() -> None:
    """Invoke dynamic commands through Telegram-compatible test doubles."""
    provider = FakeQueryProvider(
        positions=(_create_position(),),
        trades=(_create_trade(),),
        orders=(_create_order(),),
        balance=Decimal("10019.58"),
        last_price=Decimal("110"),
    )
    message = FakeMessage()
    update = cast(
        Update,
        FakeUpdate(
            message=message,
            effective_chat=FakeChat(id=_ALLOWED_CHAT_ID),
        ),
    )
    context = cast(
        ContextTypes.DEFAULT_TYPE,
        FakeContext(
            bot_data={
                ALLOWED_CHAT_IDS_KEY: frozenset({_ALLOWED_CHAT_ID}),
                BOT_CONTEXT_KEY: BotContext(
                    is_running=True,
                    query_provider=provider,
                    runtime_control=TradingRuntimeControl(),
                ),
            }
        ),
    )

    await status_command(update, context)
    await positions_command(update, context)
    await balance_command(update, context)
    await history_command(update, context)
    await orders_command(update, context)
    await pause_bot_command(update, context)
    await status_command(update, context)
    await start_bot_command(update, context)

    combined_replies = "\n".join(message.replies)

    assert len(message.replies) == 8
    assert "Open Positions:</b> 1" in combined_replies
    assert "PnL=20.00 USDT" in combined_replies
    assert "10019.58 USDT" in combined_replies
    assert "Paper Trade History" in combined_replies
    assert "19.58 USDT" in combined_replies
    assert "Order Terbaru" in combined_replies
    assert "Trading berhasil dijeda" in combined_replies
    assert "PAUSED" in combined_replies
    assert "Trading berhasil dilanjutkan" in combined_replies


def test_unauthorized_chat_cannot_query_portfolio() -> None:
    """Ignore updates whose chat ID is not explicitly allowed."""
    asyncio.run(_run_unauthorized_command_test())


async def _run_unauthorized_command_test() -> None:
    """Invoke a command from a chat outside the allow-list."""
    message = FakeMessage()
    update = cast(
        Update,
        FakeUpdate(message=message, effective_chat=FakeChat(id=99999)),
    )
    context = cast(
        ContextTypes.DEFAULT_TYPE,
        FakeContext(
            bot_data={
                ALLOWED_CHAT_IDS_KEY: frozenset({_ALLOWED_CHAT_ID}),
                BOT_CONTEXT_KEY: BotContext(),
            }
        ),
    )

    await balance_command(update, context)

    assert not message.replies
    assert is_chat_allowed(
        chat_id=_ALLOWED_CHAT_ID,
        allowed_chat_ids={_ALLOWED_CHAT_ID},
    )
    assert not is_chat_allowed(
        chat_id=99999,
        allowed_chat_ids={_ALLOWED_CHAT_ID},
    )
