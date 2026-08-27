"""Dynamic Telegram command and access-control tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast

import pytest
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from botragram.app import TradingRuntimeControl
from botragram.constants.telegram import (
    MENU_CONFIGURATION,
    MENU_DASHBOARD,
    MENU_HOME,
    MENU_MARKET_OVERVIEW,
)
from botragram.enums import (
    AuthorizationStatus,
    Interval,
    LiveRuntimeHealthStatus,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
    StrategyType,
)
from botragram.models import (
    AutonomousLiveRecoverySnapshot,
    ExecutionAuthorization,
    ExecutionAuthorizationOutcome,
    LiveRuntimeHealthSnapshot,
    LiveRuntimePositionContext,
    Order,
    Position,
    Signal,
    Trade,
    TradingDecision,
    TradingResult,
)
from botragram.telegram.access import is_chat_allowed
from botragram.telegram.callbacks import handle_callback_query
from botragram.telegram.commands import (
    balance_command,
    history_command,
    menu_message_handler,
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
    reply_markups: list[object | None] = field(default_factory=list[object | None])

    async def reply_text(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: object | None = None,
    ) -> None:
        """Capture one reply while accepting Telegram formatting arguments."""
        del parse_mode
        self.replies.append(text)
        self.reply_markups.append(reply_markup)


@dataclass(slots=True, frozen=True)
class FakeChat:
    """Minimal effective-chat representation."""

    id: int


@dataclass(slots=True)
class FakeCallbackQuery:
    """Capture callback acknowledgements and edited Telegram messages."""

    data: str
    replies: list[str] = field(default_factory=list[str])
    answer_count: int = 0

    async def answer(self) -> None:
        """Record one callback acknowledgement."""
        self.answer_count += 1

    async def edit_message_text(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: object | None = None,
    ) -> None:
        """Capture one edited callback response."""
        del parse_mode, reply_markup
        self.replies.append(text)


@dataclass(slots=True)
class FakeUpdate:
    """Minimal update shape consumed by command handlers."""

    message: FakeMessage
    effective_chat: FakeChat
    callback_query: FakeCallbackQuery | None = None


@dataclass(slots=True)
class FakeContext:
    """Minimal callback context with shared bot data."""

    bot_data: dict[str, object]
    chat_data: dict[str, object] = field(default_factory=dict[str, object])


@dataclass(slots=True, kw_only=True)
class FakeQueryProvider:
    """Return deterministic live paper portfolio data."""

    positions: tuple[Position, ...]
    trades: tuple[Trade, ...]
    orders: tuple[Order, ...]
    balance: Decimal
    last_price: Decimal
    live_runtime_health: LiveRuntimeHealthSnapshot | None = None
    autonomous_live_recovery: AutonomousLiveRecoverySnapshot | None = None
    last_price_calls: int = 0

    async def get_positions(self) -> Sequence[Position]:
        """Return active positions."""
        return self.positions

    async def get_trading_symbols(self) -> Sequence[str]:
        """Return exchange-backed symbols used by market callbacks."""
        return ("BTCUSDT", "ETHUSDT", "SOLUSDT")

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
        self.last_price_calls += 1
        return self.last_price

    def get_live_runtime_health(self) -> LiveRuntimeHealthSnapshot | None:
        """Return the configured read-only LIVE health snapshot."""
        return self.live_runtime_health

    async def get_autonomous_live_recovery(
        self,
    ) -> AutonomousLiveRecoverySnapshot | None:
        """Return configured durable recovery observability."""
        return self.autonomous_live_recovery

    def is_stream_transport_connected(self) -> bool:
        """Return a ready test WebSocket transport."""
        return True

    async def start_market_stream(self) -> bool:
        """Pretend to start a test market subscription."""
        return True

    async def wait_for_first_stream_tick(
        self,
        *,
        timeout_seconds: float = 5.0,
    ) -> bool:
        """Pretend the first stream tick arrives within the timeout."""
        return timeout_seconds > 0

    async def stop_market_stream(self) -> bool:
        """Pretend to stop a test market subscription."""
        return True


@dataclass(slots=True)
class FakeMarketTypeSwitcher:
    """Record staged and committed Telegram product selections."""

    prepared: list[MarketType] = field(default_factory=list[MarketType])
    committed: list[MarketType] = field(default_factory=list[MarketType])

    async def prepare(self, *, market_type: MarketType) -> bool:
        """Record a prepared target and require a connector change."""
        self.prepared.append(market_type)
        return True

    def commit(self, *, market_type: MarketType) -> None:
        """Record the target committed after Telegram acknowledgement."""
        self.committed.append(market_type)


@dataclass(slots=True)
class FakeExecutionAuthorizationService:
    """Record Telegram calls at the application authorization boundary."""

    authorization: ExecutionAuthorization
    execution_count: int = 0
    calls: list[str] = field(default_factory=list[str])
    fail: bool = False
    block: bool = False

    async def get(
        self,
        *,
        authorization_id: str,
    ) -> ExecutionAuthorization | None:
        """Return the configured authorization when its ID matches."""
        return (
            self.authorization
            if authorization_id == self.authorization.authorization_id
            else None
        )

    async def approve(
        self,
        *,
        authorization_id: str,
    ) -> ExecutionAuthorizationOutcome:
        """Consume approval once and simulate the application's outcome."""
        self.calls.append(f"approve:{authorization_id}")
        if self.block:
            await asyncio.Event().wait()
        if self.fail:
            raise RuntimeError("internal failure")
        if authorization_id != self.authorization.authorization_id:
            return ExecutionAuthorizationOutcome(
                authorization=None,
                trading_result=None,
            )
        if self.authorization.status is AuthorizationStatus.EXPIRED:
            return ExecutionAuthorizationOutcome(
                authorization=self.authorization,
                trading_result=None,
            )
        if self.authorization.status is AuthorizationStatus.REJECTED:
            return ExecutionAuthorizationOutcome(
                authorization=self.authorization,
                trading_result=None,
            )
        if self.execution_count:
            return ExecutionAuthorizationOutcome(
                authorization=ExecutionAuthorization(
                    authorization_id=self.authorization.authorization_id,
                    signal=self.authorization.signal,
                    status=AuthorizationStatus.APPROVED,
                    created_at=self.authorization.created_at,
                    expires_at=self.authorization.expires_at,
                ),
                trading_result=None,
            )
        self.execution_count += 1
        result = TradingResult(
            executed=True,
            decision=TradingDecision(
                should_execute=True,
                signal=self.authorization.signal,
                risk_result=None,
            ),
            order=None,
        )
        return ExecutionAuthorizationOutcome(
            authorization=self.authorization,
            trading_result=result,
        )

    async def reject(
        self,
        *,
        authorization_id: str,
    ) -> ExecutionAuthorizationOutcome:
        """Consume rejection without any execution side effect."""
        self.calls.append(f"reject:{authorization_id}")
        if authorization_id != self.authorization.authorization_id:
            return ExecutionAuthorizationOutcome(
                authorization=None,
                trading_result=None,
            )
        self.authorization = ExecutionAuthorization(
            authorization_id=self.authorization.authorization_id,
            signal=self.authorization.signal,
            status=AuthorizationStatus.REJECTED,
            created_at=self.authorization.created_at,
            expires_at=self.authorization.expires_at,
        )
        return ExecutionAuthorizationOutcome(
            authorization=self.authorization,
            trading_result=None,
        )


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


def _create_authorization(
    *,
    status: AuthorizationStatus = AuthorizationStatus.PENDING,
) -> ExecutionAuthorization:
    """Create one opaque PAPER authorization for callback tests."""
    return ExecutionAuthorization(
        authorization_id="12345678123456781234567812345678",
        signal=Signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100"),
            confidence=Decimal("0.8"),
            strategy_name="test",
            generated_at=_NOW,
        ),
        status=status,
        created_at=_NOW,
        expires_at=_NOW.replace(minute=5),
    )


def test_opportunity_callbacks_delegate_only_to_authorization_boundary() -> None:
    """Approve twice without allowing Telegram to duplicate PAPER execution."""
    asyncio.run(_run_opportunity_approval_test())


def test_opportunity_rejection_prevents_later_approval_execution() -> None:
    """Keep rejection and subsequent approval within the application lifecycle."""
    asyncio.run(_run_opportunity_rejection_test())


def test_opportunity_callbacks_fail_safely_for_invalid_and_expired_ids() -> None:
    """Render safe stale and malformed authorization callback results."""
    asyncio.run(_run_opportunity_invalid_callback_test())


def test_opportunity_callback_respects_access_and_propagates_cancellation() -> None:
    """Ignore unauthorized updates and preserve application cancellation."""
    asyncio.run(_run_opportunity_access_and_cancellation_test())


async def _run_opportunity_approval_test() -> None:
    """Deliver repeated approval callbacks to the same application boundary."""
    service = FakeExecutionAuthorizationService(
        authorization=_create_authorization(),
    )
    query = FakeCallbackQuery(
        data=f"cb_opportunity_approve_{service.authorization.authorization_id}",
    )
    context = _callback_context(service=service)
    update = cast(
        Update,
        FakeUpdate(
            message=FakeMessage(),
            effective_chat=FakeChat(id=_ALLOWED_CHAT_ID),
            callback_query=query,
        ),
    )

    await handle_callback_query(update, context)
    await handle_callback_query(update, context)

    assert service.execution_count == 1
    assert len(service.calls) == 2
    assert "Executed" in query.replies[0]
    assert "Already Processed" in query.replies[1]


async def _run_opportunity_rejection_test() -> None:
    """Reject a pending authorization before attempting approval."""
    service = FakeExecutionAuthorizationService(
        authorization=_create_authorization(),
    )
    query = FakeCallbackQuery(
        data=f"cb_opportunity_reject_{service.authorization.authorization_id}",
    )
    context = _callback_context(service=service)
    update = cast(
        Update,
        FakeUpdate(
            message=FakeMessage(),
            effective_chat=FakeChat(id=_ALLOWED_CHAT_ID),
            callback_query=query,
        ),
    )

    await handle_callback_query(update, context)
    query.data = f"cb_opportunity_approve_{service.authorization.authorization_id}"
    await handle_callback_query(update, context)

    assert service.execution_count == 0
    assert "Rejected" in query.replies[0]
    assert "Rejected" in query.replies[1]


async def _run_opportunity_invalid_callback_test() -> None:
    """Render malformed and expired authorizations without executing a signal."""
    service = FakeExecutionAuthorizationService(
        authorization=_create_authorization(status=AuthorizationStatus.EXPIRED),
    )
    query = FakeCallbackQuery(data="cb_opportunity_approve_invalid")
    context = _callback_context(service=service)
    update = cast(
        Update,
        FakeUpdate(
            message=FakeMessage(),
            effective_chat=FakeChat(id=_ALLOWED_CHAT_ID),
            callback_query=query,
        ),
    )

    await handle_callback_query(update, context)
    query.data = f"cb_opportunity_approve_{service.authorization.authorization_id}"
    await handle_callback_query(update, context)
    query.data = "cb_opportunity_approve_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    await handle_callback_query(update, context)
    service.fail = True
    query.data = f"cb_opportunity_approve_{service.authorization.authorization_id}"
    await handle_callback_query(update, context)

    assert "Invalid authorization" in query.replies[0]
    assert "Expired" in query.replies[1]
    assert "Unavailable" in query.replies[2]
    assert "Processing Failed" in query.replies[3]
    assert service.execution_count == 0


async def _run_opportunity_access_and_cancellation_test() -> None:
    """Reject unauthorized access and preserve cancellation from the boundary."""
    service = FakeExecutionAuthorizationService(
        authorization=_create_authorization(),
        block=True,
    )
    query = FakeCallbackQuery(
        data=f"cb_opportunity_approve_{service.authorization.authorization_id}",
    )
    unauthorized_update = cast(
        Update,
        FakeUpdate(
            message=FakeMessage(),
            effective_chat=FakeChat(id=99999),
            callback_query=query,
        ),
    )
    context = _callback_context(service=service)

    await handle_callback_query(unauthorized_update, context)
    assert not service.calls
    assert query.answer_count == 0

    authorized_update = cast(
        Update,
        FakeUpdate(
            message=FakeMessage(),
            effective_chat=FakeChat(id=_ALLOWED_CHAT_ID),
            callback_query=query,
        ),
    )
    task = asyncio.create_task(handle_callback_query(authorized_update, context))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


def _callback_context(
    *,
    service: FakeExecutionAuthorizationService,
) -> ContextTypes.DEFAULT_TYPE:
    """Build one authorized Telegram callback context for application fakes."""
    return cast(
        ContextTypes.DEFAULT_TYPE,
        FakeContext(
            bot_data={
                ALLOWED_CHAT_IDS_KEY: frozenset({_ALLOWED_CHAT_ID}),
                BOT_CONTEXT_KEY: BotContext(
                    execution_authorization_service=service,
                ),
            }
        ),
    )


def test_dynamic_commands_read_current_paper_portfolio() -> None:
    """Verify core commands render live query-provider values."""
    asyncio.run(_run_dynamic_command_test())


def test_menu_navigation_switches_between_compact_levels() -> None:
    """Navigate to submenus and return home without a tall keyboard."""
    asyncio.run(_run_menu_navigation_test())


def test_unconfirmed_status_hides_runtime_defaults() -> None:
    """Keep status consistent with unconfirmed configuration screens."""
    asyncio.run(_run_unconfirmed_status_test())


def test_multi_context_status_and_callback_avoid_singular_runtime_access() -> None:
    """Present every recovered context without selecting a Telegram primary."""
    asyncio.run(_run_multi_context_status_presentation_test())


async def _run_multi_context_status_presentation_test() -> None:
    """Exercise both status entry points against ambiguous legacy state."""
    contexts = (
        LiveRuntimePositionContext(
            symbol="BTCUSDT",
            interval=Interval.M1,
            strategy_type=StrategyType.EMA_CROSS,
        ),
        LiveRuntimePositionContext(
            symbol="ETHUSDT",
            interval=Interval.M5,
            strategy_type=StrategyType.EMA_SCALPING,
        ),
    )
    health = LiveRuntimeHealthSnapshot(
        status=LiveRuntimeHealthStatus.ACTIVE,
        reason=None,
        contexts=contexts,
        affected_contexts=(),
        authorization_present=True,
        authorization_exact=True,
        runner_paused=False,
        cycle_in_progress=False,
        stream_states=(),
        monitor_states=(),
    )
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=contexts)
    provider = FakeQueryProvider(
        positions=(),
        trades=(),
        orders=(),
        balance=Decimal("10000"),
        last_price=Decimal("65000"),
        live_runtime_health=health,
    )
    message = FakeMessage()
    callback = FakeCallbackQuery(data="cb_status")
    update = cast(
        Update,
        FakeUpdate(
            message=message,
            effective_chat=FakeChat(id=_ALLOWED_CHAT_ID),
            callback_query=callback,
        ),
    )
    context = cast(
        ContextTypes.DEFAULT_TYPE,
        FakeContext(
            bot_data={
                ALLOWED_CHAT_IDS_KEY: frozenset({_ALLOWED_CHAT_ID}),
                BOT_CONTEXT_KEY: BotContext(
                    is_running=True,
                    trade_mode="LIVE",
                    strategy_name=StrategyType.SUPERTREND.value,
                    query_provider=provider,
                    runtime_control=control,
                ),
            }
        ),
    )

    await status_command(update, context)
    await handle_callback_query(update, context)

    for rendered in (message.replies[-1], callback.replies[-1]):
        assert "Recovered LIVE Portfolio" in rendered
        assert "BTCUSDT" in rendered
        assert "ETHUSDT" in rendered
        assert "ema_cross" in rendered
        assert "ema_scalping" in rendered
        assert "Strategy Type: supertrend" in rendered
        assert "New LIVE Exposure: <b>DISABLED</b>" in rendered
    assert provider.last_price_calls == 0


def test_market_search_returns_selectable_exchange_symbols() -> None:
    """Search the exchange catalog from the integrated market workflow."""
    asyncio.run(_run_market_search_test())


def test_dashboard_market_is_read_only_before_configuration() -> None:
    """Keep Dashboard monitoring separate from market selection."""
    asyncio.run(_run_market_overview_test())


async def _run_unconfirmed_status_test() -> None:
    """Render account data without presenting defaults as selections."""
    provider = FakeQueryProvider(
        positions=(),
        trades=(),
        orders=(),
        balance=Decimal("10000"),
        last_price=Decimal("65000"),
    )
    message = FakeMessage()
    update = cast(
        Update,
        FakeUpdate(message=message, effective_chat=FakeChat(id=_ALLOWED_CHAT_ID)),
    )
    context = cast(
        ContextTypes.DEFAULT_TYPE,
        FakeContext(
            bot_data={
                ALLOWED_CHAT_IDS_KEY: frozenset({_ALLOWED_CHAT_ID}),
                BOT_CONTEXT_KEY: BotContext(
                    query_provider=provider,
                    runtime_control=TradingRuntimeControl(),
                ),
            }
        ),
    )

    await status_command(update, context)

    assert "Setup: <b>0/5 · INCOMPLETE</b>" in message.replies[0]
    assert "BELUM DIPILIH" not in message.replies[0]
    assert "BTCUSDT" not in message.replies[0]
    assert "ema_cross" not in message.replies[0]
    assert "Price   <code>WAITING</code>" in message.replies[0]
    assert "10000.00 USDT" in message.replies[0]


async def _run_market_overview_test() -> None:
    """Open Dashboard market data without exposing selector buttons."""
    message = FakeMessage(text=MENU_MARKET_OVERVIEW)
    update = cast(
        Update,
        FakeUpdate(message=message, effective_chat=FakeChat(id=_ALLOWED_CHAT_ID)),
    )
    context = cast(
        ContextTypes.DEFAULT_TYPE,
        FakeContext(
            bot_data={
                ALLOWED_CHAT_IDS_KEY: frozenset({_ALLOWED_CHAT_ID}),
                BOT_CONTEXT_KEY: BotContext(runtime_control=TradingRuntimeControl()),
            }
        ),
    )

    await menu_message_handler(update, context)

    assert "Market belum dikonfigurasi" in message.replies[-1]
    assert "Configuration → Select Market" in message.replies[-1]
    assert message.reply_markups[-1] is None


async def _run_market_search_test() -> None:
    """Open search, submit a keyword, and expose matching symbol callbacks."""
    provider = FakeQueryProvider(
        positions=(),
        trades=(),
        orders=(),
        balance=Decimal("10000"),
        last_price=Decimal("0"),
    )
    query = FakeCallbackQuery(data="cb_market_search")
    message = FakeMessage(text="ETH")
    update = cast(
        Update,
        FakeUpdate(
            message=message,
            effective_chat=FakeChat(id=_ALLOWED_CHAT_ID),
            callback_query=query,
        ),
    )
    fake_context = FakeContext(
        bot_data={
            ALLOWED_CHAT_IDS_KEY: frozenset({_ALLOWED_CHAT_ID}),
            BOT_CONTEXT_KEY: BotContext(
                query_provider=provider,
                runtime_control=TradingRuntimeControl(),
            ),
        }
    )
    context = cast(ContextTypes.DEFAULT_TYPE, fake_context)

    await handle_callback_query(update, context)
    message_update = cast(
        Update,
        FakeUpdate(message=message, effective_chat=FakeChat(id=_ALLOWED_CHAT_ID)),
    )
    await menu_message_handler(message_update, context)

    assert "Ketik symbol" in query.replies[-1]
    assert "Keyword: <code>ETH</code>" in message.replies[-1]
    markup = message.reply_markups[-1]
    assert isinstance(markup, InlineKeyboardMarkup)
    callbacks = {
        button.callback_data for row in markup.inline_keyboard for button in row
    }
    assert "cb_market_ethusdt" in callbacks
    assert "cb_market_search" in callbacks


async def _run_menu_navigation_test() -> None:
    """Exercise category and home reply-keyboard navigation."""
    message = FakeMessage(text=MENU_DASHBOARD)
    update = cast(
        Update,
        FakeUpdate(message=message, effective_chat=FakeChat(id=_ALLOWED_CHAT_ID)),
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

    await menu_message_handler(update, context)
    message.text = MENU_CONFIGURATION
    await menu_message_handler(update, context)
    message.text = MENU_HOME
    await menu_message_handler(update, context)

    assert all(
        isinstance(markup, ReplyKeyboardMarkup) for markup in message.reply_markups
    )
    row_counts = [
        len(markup.keyboard)
        for markup in message.reply_markups
        if isinstance(markup, ReplyKeyboardMarkup)
    ]
    assert row_counts == [3, 4, 2]
    assert "Dashboard" in message.replies[0]
    assert "Configuration" in message.replies[1]
    assert "Botragram Home" in message.replies[2]


async def _run_dynamic_command_test() -> None:
    """Invoke dynamic commands through Telegram-compatible test doubles."""
    runtime_control = TradingRuntimeControl()
    runtime_control.confirm_exchange(runtime_control.exchange_type)
    runtime_control.confirm_market_type(runtime_control.market_type)
    runtime_control.select_symbol(runtime_control.symbol)
    runtime_control.select_interval(runtime_control.interval)
    runtime_control.select_strategy(runtime_control.strategy_type)
    runtime_control.set_stream_enabled(True)
    runtime_control.record_stream_tick(price=Decimal("110"))
    runtime_control.resume()
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
                    runtime_control=runtime_control,
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


def test_open_position_allows_current_startup_values_to_be_reconfirmed() -> None:
    """Recover startup configuration without permitting position changes."""
    asyncio.run(_run_open_position_startup_recovery_test())


def test_telegram_can_request_a_futures_soft_restart() -> None:
    """Acknowledge the selected product before committing its restart."""
    asyncio.run(_run_market_type_switch_callback_test())


async def _run_market_type_switch_callback_test() -> None:
    """Select Futures through the exchange configuration callback."""
    switcher = FakeMarketTypeSwitcher()
    query = FakeCallbackQuery(data="cb_product_futures")
    update = cast(
        Update,
        FakeUpdate(
            message=FakeMessage(),
            effective_chat=FakeChat(id=_ALLOWED_CHAT_ID),
            callback_query=query,
        ),
    )
    context = cast(
        ContextTypes.DEFAULT_TYPE,
        FakeContext(
            bot_data={
                ALLOWED_CHAT_IDS_KEY: frozenset({_ALLOWED_CHAT_ID}),
                BOT_CONTEXT_KEY: BotContext(
                    runtime_control=TradingRuntimeControl(),
                    market_type_switcher=switcher,
                ),
            }
        ),
    )

    await handle_callback_query(update, context)

    assert switcher.prepared == [MarketType.FUTURES]
    assert switcher.committed == [MarketType.FUTURES]
    assert "Binance Futures" in query.replies[-1]


async def _run_open_position_startup_recovery_test() -> None:
    """Confirm active selections and retain guards for different values."""
    runtime_control = TradingRuntimeControl()
    provider = FakeQueryProvider(
        positions=(_create_position(),),
        trades=(),
        orders=(),
        balance=Decimal("9000"),
        last_price=Decimal("110"),
    )
    query = FakeCallbackQuery(data="cb_market_btcusdt")
    update = cast(
        Update,
        FakeUpdate(
            message=FakeMessage(),
            effective_chat=FakeChat(id=_ALLOWED_CHAT_ID),
            callback_query=query,
        ),
    )
    context = cast(
        ContextTypes.DEFAULT_TYPE,
        FakeContext(
            bot_data={
                ALLOWED_CHAT_IDS_KEY: frozenset({_ALLOWED_CHAT_ID}),
                BOT_CONTEXT_KEY: BotContext(
                    query_provider=provider,
                    runtime_control=runtime_control,
                ),
            }
        ),
    )

    current_callbacks = (
        "cb_market_btcusdt",
        "cb_strategy_ema_cross",
        "cb_interval_15m",
    )

    for callback_data in current_callbacks:
        query.data = callback_data
        await handle_callback_query(update, context)

    assert runtime_control.get_missing_configuration_requirements() == (
        "exchange",
        "market type",
    )
    assert not any("Tutup semua posisi" in reply for reply in query.replies)

    blocked_callbacks = (
        ("cb_market_ethusdt", "market"),
        ("cb_strategy_supertrend", "strategy"),
        ("cb_interval_1m", "interval"),
    )

    for callback_data, selection_name in blocked_callbacks:
        query.data = callback_data
        await handle_callback_query(update, context)
        assert "Tutup semua posisi" in query.replies[-1]
        assert selection_name in query.replies[-1]

    assert runtime_control.symbol == "BTCUSDT"
    assert runtime_control.strategy_type.value == "ema_cross"
    assert runtime_control.interval.value == "15m"
    assert "110.00 USDT" in query.replies[0]

    runtime_control.confirm_exchange(runtime_control.exchange_type)
    runtime_control.confirm_market_type(runtime_control.market_type)
    runtime_control.set_stream_enabled(True)
    runtime_control.record_stream_tick(price=Decimal("110"))

    assert runtime_control.resume()
    assert not runtime_control.is_paused


def test_start_bot_command_reports_incomplete_startup_gate() -> None:
    """Keep trading paused and return the Telegram configuration checklist."""
    asyncio.run(_run_incomplete_startup_gate_test())


async def _run_incomplete_startup_gate_test() -> None:
    """Attempt to start an unconfigured runtime from an authorized chat."""
    runtime_control = TradingRuntimeControl()
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
                BOT_CONTEXT_KEY: BotContext(runtime_control=runtime_control),
            }
        ),
    )

    await start_bot_command(update, context)

    assert runtime_control.is_paused
    assert len(message.replies) == 1
    assert "Trading belum dapat dimulai" in message.replies[0]
    assert "Startup Configuration" in message.replies[0]
    assert message.replies[0].count("BELUM DIPILIH") == 5
    assert "BTCUSDT" not in message.replies[0]
    assert "ema_cross" not in message.replies[0]


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
