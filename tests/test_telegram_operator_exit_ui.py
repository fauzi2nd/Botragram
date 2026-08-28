"""Telegram operator-exit UI keeps financial actions explicit."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from botragram.app import TradingRuntimeControl
from botragram.enums import (
    ExchangeEnvironment,
    ExecutionPolicy,
    MarketType,
    OperatorExitStatus,
    OperatorExitType,
    PositionSide,
    TradeMode,
)
from botragram.exceptions import (
    ExecutionPolicySwitchBlockedError,
    OperatorExitConfirmationUnavailableError,
)
from botragram.models import (
    OperatorExitConfirmation,
    OperatorExitSnapshot,
    Position,
)
from botragram.telegram.callbacks import handle_callback_query
from botragram.telegram.commands import positions_command
from botragram.telegram.context import (
    ALLOWED_CHAT_IDS_KEY,
    BOT_CONTEXT_KEY,
    BotContext,
)
from botragram.telegram.keyboards import (
    get_operator_exit_confirmation_keyboard,
)

_CHAT_ID = 12345
_NOW = datetime(2026, 8, 28, tzinfo=UTC)
_CONFIRMATION_ID = "12345678123456781234567812345678"


def _position() -> Position:
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("0.01"),
        entry_price=Decimal("100"),
        current_price=Decimal("101"),
        unrealized_pnl=Decimal("0.01"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )


@dataclass(slots=True)
class _Message:
    replies: list[str] = field(default_factory=list[str])
    reply_markups: list[object | None] = field(default_factory=list[object | None])

    async def reply_text(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: object | None = None,
    ) -> None:
        del parse_mode
        self.replies.append(text)
        self.reply_markups.append(reply_markup)


@dataclass(slots=True, frozen=True)
class _Chat:
    id: int


@dataclass(slots=True)
class _Query:
    data: str
    replies: list[str] = field(default_factory=list[str])
    reply_markups: list[object | None] = field(default_factory=list[object | None])
    answer_count: int = 0

    async def answer(self) -> None:
        self.answer_count += 1

    async def edit_message_text(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: object | None = None,
    ) -> None:
        del parse_mode
        self.replies.append(text)
        self.reply_markups.append(reply_markup)


@dataclass(slots=True)
class _Update:
    message: _Message
    effective_chat: _Chat
    callback_query: _Query | None = None


@dataclass(slots=True)
class _Context:
    bot_data: dict[str, object]
    args: list[str] = field(default_factory=list[str])


@dataclass(slots=True)
class _OperatorService:
    typed: bool = False
    confirmation_unavailable: bool = False
    request_calls: list[str] = field(default_factory=list[str])
    confirm_calls: list[str] = field(default_factory=list[str])
    cancel_calls: list[str] = field(default_factory=list[str])

    def challenge(
        self,
        *,
        operation_type: OperatorExitType,
        target: ExecutionPolicy | None = None,
    ) -> OperatorExitConfirmation:
        return OperatorExitConfirmation(
            confirmation_id=_CONFIRMATION_ID,
            operation_type=operation_type,
            environment="MAINNET" if self.typed else "TESTNET",
            symbols=("BTCUSDT",),
            required_token="FLATTEN 1" if self.typed else "CONFIRM",
            requires_typed_confirmation=self.typed,
            expires_at=_NOW + timedelta(minutes=5),
            target_execution_policy=target,
        )

    async def get_positions(self) -> tuple[Position, ...]:
        return (_position(),)

    async def get_snapshot(self) -> OperatorExitSnapshot:
        return OperatorExitSnapshot(
            status=OperatorExitStatus.AWAITING_CONFIRMATION,
            trade_mode=TradeMode.LIVE,
            exchange_environment=(
                ExchangeEnvironment.MAINNET
                if self.typed
                else ExchangeEnvironment.TESTNET
            ),
            positions=(_position(),),
        )

    async def request_close_position(
        self,
        *,
        symbol: str,
        requested_by: str,
        auto_pause: bool = False,
    ) -> OperatorExitConfirmation:
        self.request_calls.append(f"position:{symbol}:{requested_by}:{auto_pause}")
        return self.challenge(operation_type=OperatorExitType.CLOSE_POSITION)

    async def request_close_all(
        self,
        *,
        requested_by: str,
        target_execution_policy: ExecutionPolicy | None = None,
        auto_pause: bool = False,
    ) -> OperatorExitConfirmation:
        target = (
            target_execution_policy.value
            if target_execution_policy is not None
            else "none"
        )
        self.request_calls.append(f"all:{requested_by}:{target}:{auto_pause}")
        return self.challenge(
            operation_type=(
                OperatorExitType.FLATTEN_AND_SWITCH
                if target_execution_policy is not None
                else OperatorExitType.CLOSE_ALL
            ),
            target=target_execution_policy,
        )

    async def confirm(
        self,
        *,
        confirmation_id: str,
        requested_by: str,
        token: str | None = None,
    ) -> OperatorExitSnapshot:
        if self.confirmation_unavailable:
            raise OperatorExitConfirmationUnavailableError(
                "Operator-exit confirmation is unavailable"
            )
        self.confirm_calls.append(f"{confirmation_id}:{requested_by}:{token}")
        return OperatorExitSnapshot(
            status=OperatorExitStatus.COMPLETE,
            trade_mode=TradeMode.LIVE,
            exchange_environment=ExchangeEnvironment.TESTNET,
            positions=(),
        )

    async def cancel_confirmation(
        self,
        *,
        confirmation_id: str,
        requested_by: str,
    ) -> None:
        self.cancel_calls.append(f"{confirmation_id}:{requested_by}")


@dataclass(slots=True)
class _Switcher:
    execution_policy: ExecutionPolicy = ExecutionPolicy.AUTONOMOUS_LIVE
    unexpected_failure: bool = False
    prepare_calls: int = 0
    commit_calls: int = 0

    @property
    def current_execution_policy(self) -> ExecutionPolicy:
        return self.execution_policy

    def available_execution_policies(self) -> tuple[ExecutionPolicy, ...]:
        return (
            ExecutionPolicy.AUTONOMOUS_LIVE,
            ExecutionPolicy.SINGLE_SYMBOL,
        )

    async def prepare(self, *, market_type: MarketType) -> bool:
        del market_type
        return False

    def commit(self, *, market_type: MarketType) -> None:
        del market_type

    async def prepare_execution_policy(
        self,
        *,
        execution_policy: ExecutionPolicy,
    ) -> bool:
        del execution_policy
        self.prepare_calls += 1
        if self.unexpected_failure:
            raise OSError("configured unexpected switch failure")
        raise ExecutionPolicySwitchBlockedError(
            "Close every active position before switching trading mode",
            active_position_count=1,
        )

    def commit_execution_policy(
        self,
        *,
        execution_policy: ExecutionPolicy,
    ) -> None:
        self.commit_calls += 1
        self.execution_policy = execution_policy


def _context(
    *,
    service: _OperatorService,
    switcher: _Switcher | None = None,
) -> ContextTypes.DEFAULT_TYPE:
    return cast(
        ContextTypes.DEFAULT_TYPE,
        _Context(
            bot_data={
                ALLOWED_CHAT_IDS_KEY: frozenset({_CHAT_ID}),
                BOT_CONTEXT_KEY: BotContext(
                    trade_mode="LIVE",
                    execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
                    positions=(_position(),),
                    runtime_control=TradingRuntimeControl(),
                    market_type_switcher=switcher,
                    operator_exit_service=service,
                ),
            }
        ),
    )


@pytest.mark.asyncio
async def test_positions_render_explicit_exit_controls_without_mutation() -> None:
    service = _OperatorService()
    message = _Message()
    update = cast(
        Update,
        _Update(message=message, effective_chat=_Chat(id=_CHAT_ID)),
    )

    await positions_command(update, _context(service=service))

    assert not service.request_calls
    markup = message.reply_markups[-1]
    assert isinstance(markup, InlineKeyboardMarkup)
    callbacks = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if isinstance(button.callback_data, str)
    }
    assert "cb_operator_exit_close_btcusdt" in callbacks
    assert "cb_operator_exit_close_all" in callbacks


def test_mainnet_confirmation_has_no_inline_financial_confirm() -> None:
    challenge = _OperatorService(typed=True).challenge(
        operation_type=OperatorExitType.CLOSE_ALL
    )
    markup = get_operator_exit_confirmation_keyboard(confirmation=challenge)
    callbacks = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if isinstance(button.callback_data, str)
    }

    assert not any(
        value is not None and value.startswith("cb_operator_exit_confirm_")
        for value in callbacks
    )
    assert f"cb_operator_exit_cancel_{_CONFIRMATION_ID}" in callbacks


@pytest.mark.asyncio
async def test_testnet_inline_confirm_uses_chat_bound_confirmation() -> None:
    service = _OperatorService()
    query = _Query(data=f"cb_operator_exit_confirm_{_CONFIRMATION_ID}")
    update = cast(
        Update,
        _Update(
            message=_Message(),
            effective_chat=_Chat(id=_CHAT_ID),
            callback_query=query,
        ),
    )

    await handle_callback_query(update, _context(service=service))

    assert service.confirm_calls == [f"{_CONFIRMATION_ID}:telegram:{_CHAT_ID}:CONFIRM"]
    assert "status=complete" in query.replies[-1]

    service.confirmation_unavailable = True
    await handle_callback_query(update, _context(service=service))

    assert "Reopen Trading Mode or Positions" in query.replies[-1]
    assert "No action was taken" in query.replies[-1]
    assert service.confirm_calls == [f"{_CONFIRMATION_ID}:telegram:{_CHAT_ID}:CONFIRM"]


@pytest.mark.asyncio
async def test_mode_switch_with_position_offers_guarded_flatten_transition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = _OperatorService()
    switcher = _Switcher()
    query = _Query(data="cb_policy_confirm_single_symbol")
    update = cast(
        Update,
        _Update(
            message=_Message(),
            effective_chat=_Chat(id=_CHAT_ID),
            callback_query=query,
        ),
    )

    caplog.set_level(logging.ERROR, logger="botragram.telegram.callbacks")
    await handle_callback_query(
        update,
        _context(service=service, switcher=switcher),
    )

    markup = query.reply_markups[-1]
    assert isinstance(markup, InlineKeyboardMarkup)
    callbacks = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if isinstance(button.callback_data, str)
    }
    assert "cb_operator_exit_flatten_switch_single_symbol" in callbacks
    assert not service.request_calls
    assert switcher.prepare_calls == 1
    assert switcher.commit_calls == 0
    assert not caplog.records

    query.data = "cb_operator_exit_flatten_switch_single_symbol"
    await handle_callback_query(
        update,
        _context(service=service, switcher=switcher),
    )

    assert service.request_calls == [f"all:telegram:{_CHAT_ID}:single_symbol:True"]
    confirmation_markup = query.reply_markups[-1]
    assert isinstance(confirmation_markup, InlineKeyboardMarkup)
    confirmation_callbacks = {
        button.callback_data
        for row in confirmation_markup.inline_keyboard
        for button in row
        if isinstance(button.callback_data, str)
    }
    assert f"cb_operator_exit_confirm_{_CONFIRMATION_ID}" in (confirmation_callbacks)

    caplog.clear()
    switcher.unexpected_failure = True
    query.data = "cb_policy_confirm_single_symbol"
    await handle_callback_query(update, _context(service=service, switcher=switcher))

    assert "failed unexpectedly" in query.replies[-1]
    assert query.reply_markups[-1] is None
    assert service.request_calls == [f"all:telegram:{_CHAT_ID}:single_symbol:True"]
    assert switcher.prepare_calls == 2
    assert switcher.commit_calls == 0
    assert any(
        record.message == "Telegram execution-policy switch validation failed"
        for record in caplog.records
    )
