from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

EXPECTED_HEAD = "6b563280d45e71e4247a850b526db3ff6492e52f"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def replace_once(root: Path, path: str, old: str, new: str) -> None:
    file_path = root / path
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected one replacement in {path}, found {count}: "
            f"{old.splitlines()[0]!r}"
        )
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def write_new(root: Path, path: str, content: str) -> None:
    file_path = root / path
    if file_path.exists():
        if file_path.read_text(encoding="utf-8") == content:
            return
        raise RuntimeError(f"Refusing to overwrite unexpected existing file: {path}")
    file_path.write_text(content, encoding="utf-8", newline="\n")


def patch_keyboards(root: Path) -> None:
    path = "botragram/telegram/keyboards.py"
    replace_once(
        root,
        path,
        "from botragram.enums import ExecutionPolicy, MarketType\n",
        "from botragram.enums import ExecutionPolicy, MarketType\n"
        "from botragram.models import OperatorExitConfirmation, Position\n",
    )
    replace_once(
        root,
        path,
        '    "get_market_search_keyboard",\n    "get_strategy_keyboard",\n',
        '    "get_market_search_keyboard",\n'
        '    "get_operator_exit_confirmation_keyboard",\n'
        '    "get_operator_exit_positions_keyboard",\n'
        '    "get_operator_flatten_switch_keyboard",\n'
        '    "get_strategy_keyboard",\n',
    )
    marker = "\ndef get_execution_policy_keyboard(\n"
    block = dedent(
        '''
        def get_operator_exit_positions_keyboard(
            *,
            positions: Sequence[Position],
        ) -> InlineKeyboardMarkup:
            """Return explicit per-position and whole-portfolio exit controls."""
            rows = [
                [
                    InlineKeyboardButton(
                        f"⚠️ Close {position.symbol.upper()}",
                        callback_data=(
                            f"cb_operator_exit_close_{position.symbol.strip().lower()}"
                        ),
                    )
                ]
                for position in positions
            ]
            if positions:
                rows.append(
                    [
                        InlineKeyboardButton(
                            "⚠️ Close All Positions",
                            callback_data="cb_operator_exit_close_all",
                        )
                    ]
                )
            return InlineKeyboardMarkup(rows)


        def get_operator_exit_confirmation_keyboard(
            *,
            confirmation: OperatorExitConfirmation,
        ) -> InlineKeyboardMarkup:
            """Return safe confirmation controls without weakening MAINNET typing."""
            rows: list[list[InlineKeyboardButton]] = []
            if not confirmation.requires_typed_confirmation:
                rows.append(
                    [
                        InlineKeyboardButton(
                            "✅ Confirm Exit",
                            callback_data=(
                                "cb_operator_exit_confirm_"
                                f"{confirmation.confirmation_id}"
                            ),
                        )
                    ]
                )
            rows.append(
                [
                    InlineKeyboardButton(
                        "Cancel",
                        callback_data=(
                            "cb_operator_exit_cancel_"
                            f"{confirmation.confirmation_id}"
                        ),
                    )
                ]
            )
            return InlineKeyboardMarkup(rows)


        def get_operator_flatten_switch_keyboard(
            *,
            execution_policy: ExecutionPolicy,
        ) -> InlineKeyboardMarkup:
            """Offer an explicit financial transition when positions block switching."""
            return InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⚠️ Close All & Switch",
                            callback_data=(
                                "cb_operator_exit_flatten_switch_"
                                f"{execution_policy.value}"
                            ),
                        )
                    ],
                    [InlineKeyboardButton("Cancel", callback_data="cb_policy_cancel")],
                ]
            )


        '''
    )
    replace_once(root, path, marker, "\n" + block + "def get_execution_policy_keyboard(\n")


def patch_operator_commands(root: Path) -> None:
    path = "botragram/telegram/operator_exit_commands.py"
    replace_once(
        root,
        path,
        "from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext\n",
        "from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext\n"
        "from botragram.telegram.keyboards import (\n"
        "    get_operator_exit_confirmation_keyboard,\n"
        ")\n",
    )
    replace_once(
        root,
        path,
        '    "exit_status_command",\n]\n',
        '    "exit_status_command",\n'
        '    "format_operator_exit_confirmation",\n'
        '    "format_operator_exit_snapshot",\n'
        '    "get_operator_exit_requester",\n'
        ']\n',
    )
    replace_once(
        root,
        path,
        "def _get_requester(update: Update) -> str | None:\n"
        "    chat = update.effective_chat\n"
        '    return f"telegram:{chat.id}" if chat is not None else None\n',
        "def get_operator_exit_requester(update: Update) -> str | None:\n"
        "    \"\"\"Return the chat-bound operator identity used by confirmations.\"\"\"\n"
        "    chat = update.effective_chat\n"
        '    return f"telegram:{chat.id}" if chat is not None else None\n',
    )
    replace_once(
        root,
        path,
        "def _format_confirmation(challenge: OperatorExitConfirmation) -> str:\n",
        "def format_operator_exit_confirmation(\n"
        "    challenge: OperatorExitConfirmation,\n"
        ") -> str:\n",
    )
    replace_once(
        root,
        path,
        '        "No close order has been sent yet.\\n"\n'
        '        "Confirm exactly with:\\n"\n'
        '        f"/confirmexit {challenge.confirmation_id} {challenge.required_token}\\n"\n'
        '        "Cancel with:\\n"\n'
        '        f"/cancelexit {challenge.confirmation_id}"\n',
        '        "No close order has been sent yet.\\n"\n'
        '        + (\n'
        '            "MAINNET requires typed confirmation exactly with:\\n"\n'
        '            if challenge.requires_typed_confirmation\n'
        '            else "Confirm with the button below or exactly with:\\n"\n'
        '        )\n'
        '        + f"/confirmexit {challenge.confirmation_id} "\n'
        '        f"{challenge.required_token}\\n"\n'
        '        + "Cancel with:\\n"\n'
        '        + f"/cancelexit {challenge.confirmation_id}"\n',
    )
    replace_once(
        root,
        path,
        "def _format_snapshot(snapshot: OperatorExitSnapshot) -> str:\n",
        "def format_operator_exit_snapshot(snapshot: OperatorExitSnapshot) -> str:\n",
    )
    text_path = root / path
    text = text_path.read_text(encoding="utf-8")
    text = text.replace("_get_requester(update)", "get_operator_exit_requester(update)")
    text = text.replace("_format_confirmation(challenge)", "format_operator_exit_confirmation(challenge)")
    text = text.replace("_format_snapshot(snapshot)", "format_operator_exit_snapshot(snapshot)")
    text = text.replace(
        "            auto_pause=True,\n",
        "            auto_pause=False,\n",
        2,
    )
    # Flatten-and-switch remains the sole command path allowed to auto-pause.
    needle = """        challenge = await service.request_close_all(
            requested_by=requester,
            target_execution_policy=target,
            auto_pause=False,
        )
"""
    if needle not in text:
        raise RuntimeError("Expected flatten-and-switch request block after normalization")
    text = text.replace(needle, needle.replace("auto_pause=False", "auto_pause=True"), 1)
    # Add safe inline markup to every generated challenge.
    text = text.replace(
        "    await message.reply_text(format_operator_exit_confirmation(challenge))\n",
        "    await message.reply_text(\n"
        "        format_operator_exit_confirmation(challenge),\n"
        "        reply_markup=get_operator_exit_confirmation_keyboard(\n"
        "            confirmation=challenge,\n"
        "        ),\n"
        "    )\n",
    )
    text_path.write_text(text, encoding="utf-8", newline="\n")


def patch_commands(root: Path) -> None:
    path = "botragram/telegram/commands.py"
    replace_once(
        root,
        path,
        "    get_market_search_keyboard,\n    get_strategy_keyboard,\n",
        "    get_market_search_keyboard,\n"
        "    get_operator_exit_positions_keyboard,\n"
        "    get_strategy_keyboard,\n",
    )
    replace_once(
        root,
        path,
        "        msg = get_positions_message(positions)\n"
        "        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)\n",
        "        msg = get_positions_message(positions)\n"
        "        exit_markup = (\n"
        "            get_operator_exit_positions_keyboard(positions=positions)\n"
        "            if ctx.operator_exit_service is not None and positions\n"
        "            else None\n"
        "        )\n"
        "        await update.message.reply_text(\n"
        "            msg,\n"
        "            parse_mode=DEFAULT_PARSE_MODE,\n"
        "            reply_markup=exit_markup,\n"
        "        )\n",
    )


def patch_callbacks(root: Path) -> None:
    path = "botragram/telegram/callbacks.py"
    replace_once(
        root,
        path,
        "    get_market_search_keyboard,\n    get_strategy_keyboard,\n",
        "    get_market_search_keyboard,\n"
        "    get_operator_exit_confirmation_keyboard,\n"
        "    get_operator_flatten_switch_keyboard,\n"
        "    get_strategy_keyboard,\n",
    )
    replace_once(
        root,
        path,
        "from botragram.telegram.messages import (\n",
        "from botragram.telegram.operator_exit_commands import (\n"
        "    format_operator_exit_confirmation,\n"
        "    format_operator_exit_snapshot,\n"
        "    get_operator_exit_requester,\n"
        ")\n"
        "from botragram.telegram.messages import (\n",
    )
    replace_once(
        root,
        path,
        '_POLICY_CANCEL_CALLBACK: Final[str] = "cb_policy_cancel"\n',
        '_POLICY_CANCEL_CALLBACK: Final[str] = "cb_policy_cancel"\n'
        '_OPERATOR_CLOSE_CALLBACK_PREFIX: Final[str] = "cb_operator_exit_close_"\n'
        '_OPERATOR_CLOSE_ALL_CALLBACK: Final[str] = "cb_operator_exit_close_all"\n'
        '_OPERATOR_CONFIRM_CALLBACK_PREFIX: Final[str] = "cb_operator_exit_confirm_"\n'
        '_OPERATOR_CANCEL_CALLBACK_PREFIX: Final[str] = "cb_operator_exit_cancel_"\n'
        '_OPERATOR_FLATTEN_SWITCH_PREFIX: Final[str] = (\n'
        '    "cb_operator_exit_flatten_switch_"\n'
        ')\n',
    )
    marker = "\n    if data.startswith(_POLICY_SELECT_CALLBACK_PREFIX):\n"
    block = dedent(
        '''
            service = bot_context.operator_exit_service
            requester = get_operator_exit_requester(update)

            if data == _OPERATOR_CLOSE_ALL_CALLBACK:
                if service is None or requester is None:
                    await query.edit_message_text("Operator exit controls are unavailable.")
                    return
                try:
                    challenge = await service.request_close_all(
                        requested_by=requester,
                        auto_pause=False,
                    )
                except (RuntimeError, ValueError) as error:
                    await query.edit_message_text(
                        f"⚠️ <b>{escape(str(error))}</b>",
                        parse_mode=DEFAULT_PARSE_MODE,
                    )
                    return
                await query.edit_message_text(
                    format_operator_exit_confirmation(challenge),
                    parse_mode=DEFAULT_PARSE_MODE,
                    reply_markup=get_operator_exit_confirmation_keyboard(
                        confirmation=challenge,
                    ),
                )
                return

            if data.startswith(_OPERATOR_CLOSE_CALLBACK_PREFIX):
                if service is None or requester is None:
                    await query.edit_message_text("Operator exit controls are unavailable.")
                    return
                symbol = data.removeprefix(_OPERATOR_CLOSE_CALLBACK_PREFIX).strip().upper()
                try:
                    challenge = await service.request_close_position(
                        symbol=symbol,
                        requested_by=requester,
                        auto_pause=False,
                    )
                except (RuntimeError, ValueError) as error:
                    await query.edit_message_text(
                        f"⚠️ <b>{escape(str(error))}</b>",
                        parse_mode=DEFAULT_PARSE_MODE,
                    )
                    return
                await query.edit_message_text(
                    format_operator_exit_confirmation(challenge),
                    parse_mode=DEFAULT_PARSE_MODE,
                    reply_markup=get_operator_exit_confirmation_keyboard(
                        confirmation=challenge,
                    ),
                )
                return

            if data.startswith(_OPERATOR_CONFIRM_CALLBACK_PREFIX):
                if service is None or requester is None:
                    await query.edit_message_text("Operator exit controls are unavailable.")
                    return
                confirmation_id = data.removeprefix(
                    _OPERATOR_CONFIRM_CALLBACK_PREFIX
                ).strip().lower()
                try:
                    snapshot = await service.confirm(
                        confirmation_id=confirmation_id,
                        requested_by=requester,
                        token="CONFIRM",
                    )
                except (RuntimeError, ValueError) as error:
                    await query.edit_message_text(
                        f"⚠️ <b>{escape(str(error))}</b>",
                        parse_mode=DEFAULT_PARSE_MODE,
                    )
                    return
                await query.edit_message_text(
                    format_operator_exit_snapshot(snapshot),
                    parse_mode=DEFAULT_PARSE_MODE,
                )
                return

            if data.startswith(_OPERATOR_CANCEL_CALLBACK_PREFIX):
                if service is None or requester is None:
                    await query.edit_message_text("Operator exit controls are unavailable.")
                    return
                confirmation_id = data.removeprefix(
                    _OPERATOR_CANCEL_CALLBACK_PREFIX
                ).strip().lower()
                try:
                    await service.cancel_confirmation(
                        confirmation_id=confirmation_id,
                        requested_by=requester,
                    )
                except (RuntimeError, ValueError) as error:
                    await query.edit_message_text(
                        f"⚠️ <b>{escape(str(error))}</b>",
                        parse_mode=DEFAULT_PARSE_MODE,
                    )
                    return
                await query.edit_message_text(
                    "Operator exit confirmation cancelled. No close order sent."
                )
                return

            if data.startswith(_OPERATOR_FLATTEN_SWITCH_PREFIX):
                if service is None or requester is None:
                    await query.edit_message_text("Operator exit controls are unavailable.")
                    return
                target = _parse_execution_policy_callback(
                    callback_data=data,
                    prefix=_OPERATOR_FLATTEN_SWITCH_PREFIX,
                )
                if target is None:
                    await query.edit_message_text("Invalid execution-policy target.")
                    return
                try:
                    challenge = await service.request_close_all(
                        requested_by=requester,
                        target_execution_policy=target,
                        auto_pause=True,
                    )
                except (RuntimeError, ValueError) as error:
                    await query.edit_message_text(
                        f"⚠️ <b>{escape(str(error))}</b>",
                        parse_mode=DEFAULT_PARSE_MODE,
                    )
                    return
                await query.edit_message_text(
                    format_operator_exit_confirmation(challenge),
                    parse_mode=DEFAULT_PARSE_MODE,
                    reply_markup=get_operator_exit_confirmation_keyboard(
                        confirmation=challenge,
                    ),
                )
                return

        '''
    )
    replace_once(root, path, marker, "\n" + block + "    if data.startswith(_POLICY_SELECT_CALLBACK_PREFIX):\n")

    old_error = dedent(
        '''
                except Exception as error:
                    _LOGGER.exception("Telegram execution-policy switch validation failed")
                    await query.edit_message_text(
                        f"⚠️ <b>{escape(str(error))}</b>",
                        parse_mode=DEFAULT_PARSE_MODE,
                        reply_markup=get_execution_policy_keyboard(
                            current_policy=bot_context.execution_policy,
                            available_policies=switcher.available_execution_policies(),
                        ),
                    )
                    return
        '''
    ).rstrip("\n")
    new_error = dedent(
        '''
                except Exception as error:
                    _LOGGER.exception("Telegram execution-policy switch validation failed")
                    operator_service = bot_context.operator_exit_service
                    positions = ()
                    if operator_service is not None:
                        try:
                            positions = tuple(await operator_service.get_positions())
                        except Exception:
                            _LOGGER.exception(
                                "Telegram operator-exit position lookup failed"
                            )
                    if positions:
                        await query.edit_message_text(
                            f"⚠️ <b>{escape(str(error))}</b>\n\n"
                            f"{len(positions)} active position(s) block this switch. "
                            "Botragram can flatten them through the guarded operator-exit "
                            "workflow and switch only after zero exposure is verified.",
                            parse_mode=DEFAULT_PARSE_MODE,
                            reply_markup=get_operator_flatten_switch_keyboard(
                                execution_policy=target,
                            ),
                        )
                        return
                    await query.edit_message_text(
                        f"⚠️ <b>{escape(str(error))}</b>",
                        parse_mode=DEFAULT_PARSE_MODE,
                        reply_markup=get_execution_policy_keyboard(
                            current_policy=bot_context.execution_policy,
                            available_policies=switcher.available_execution_policies(),
                        ),
                    )
                    return
        '''
    ).rstrip("\n")
    replace_once(root, path, old_error, new_error)


def patch_context(root: Path) -> None:
    path = "botragram/telegram/context.py"
    replace_once(
        root,
        path,
        "    async def get_snapshot(self) -> OperatorExitSnapshot:\n"
        "        \"\"\"Return truthful durable operator-exit state.\"\"\"\n"
        "        ...\n\n",
        "    async def get_snapshot(self) -> OperatorExitSnapshot:\n"
        "        \"\"\"Return truthful durable operator-exit state.\"\"\"\n"
        "        ...\n\n"
        "    async def get_positions(self) -> tuple[Position, ...]:\n"
        "        \"\"\"Return mode-appropriate authoritative positions.\"\"\"\n"
        "        ...\n\n",
    )


def patch_bot_commands(root: Path) -> None:
    path = "botragram/telegram/bot.py"
    replace_once(
        root,
        path,
        '                    BotCommand("risklimits", "Lihat limit entry runtime"),\n',
        '                    BotCommand("risklimits", "Lihat limit entry runtime"),\n'
        '                    BotCommand("exitstatus", "Lihat status operator exit"),\n'
        '                    BotCommand("closeposition", "Tutup satu posisi saat PAUSED"),\n'
        '                    BotCommand("closeall", "Tutup semua posisi saat PAUSED"),\n'
        '                    BotCommand("closeandswitch", "Flatten lalu ganti trading mode"),\n',
    )


def add_tests(root: Path) -> None:
    write_new(
        root,
        "tests/test_telegram_operator_exit_ui.py",
        dedent(
            '''\
            """Telegram operator-exit UI keeps financial actions explicit."""

            from __future__ import annotations

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
                OperatorExitStatus,
                OperatorExitType,
                PositionSide,
                TradeMode,
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
            class _QueryProvider:
                async def get_positions(self) -> tuple[Position, ...]:
                    return (_position(),)


            @dataclass(slots=True)
            class _OperatorService:
                typed: bool = False
                request_calls: list[str] = field(default_factory=list[str])
                confirm_calls: list[str] = field(default_factory=list[str])
                cancel_calls: list[str] = field(default_factory=list[str])

                def _challenge(
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
                    self.request_calls.append(
                        f"position:{symbol}:{requested_by}:{auto_pause}"
                    )
                    return self._challenge(
                        operation_type=OperatorExitType.CLOSE_POSITION
                    )

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
                    self.request_calls.append(
                        f"all:{requested_by}:{target}:{auto_pause}"
                    )
                    return self._challenge(
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
                    self.confirm_calls.append(
                        f"{confirmation_id}:{requested_by}:{token}"
                    )
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

                @property
                def current_execution_policy(self) -> ExecutionPolicy:
                    return self.execution_policy

                def available_execution_policies(self) -> tuple[ExecutionPolicy, ...]:
                    return (
                        ExecutionPolicy.AUTONOMOUS_LIVE,
                        ExecutionPolicy.SINGLE_SYMBOL,
                    )

                async def prepare(self, *, market_type: object) -> bool:
                    del market_type
                    return False

                def commit(self, *, market_type: object) -> None:
                    del market_type

                async def prepare_execution_policy(
                    self,
                    *,
                    execution_policy: ExecutionPolicy,
                ) -> bool:
                    del execution_policy
                    raise RuntimeError(
                        "Close every active position before switching trading mode"
                    )

                def commit_execution_policy(
                    self,
                    *,
                    execution_policy: ExecutionPolicy,
                ) -> None:
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
                                query_provider=cast(object, _QueryProvider()),
                                runtime_control=TradingRuntimeControl(),
                                market_type_switcher=(
                                    cast(object, switcher)
                                    if switcher is not None
                                    else None
                                ),
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
                }
                assert "cb_operator_exit_close_btcusdt" in callbacks
                assert "cb_operator_exit_close_all" in callbacks


            def test_mainnet_confirmation_has_no_inline_financial_confirm() -> None:
                challenge = _OperatorService(typed=True)._challenge(
                    operation_type=OperatorExitType.CLOSE_ALL
                )
                markup = get_operator_exit_confirmation_keyboard(
                    confirmation=challenge
                )
                callbacks = {
                    button.callback_data
                    for row in markup.inline_keyboard
                    for button in row
                }

                assert not any(
                    value is not None
                    and value.startswith("cb_operator_exit_confirm_")
                    for value in callbacks
                )
                assert f"cb_operator_exit_cancel_{_CONFIRMATION_ID}" in callbacks


            @pytest.mark.asyncio
            async def test_testnet_inline_confirm_uses_chat_bound_confirmation() -> None:
                service = _OperatorService()
                query = _Query(
                    data=f"cb_operator_exit_confirm_{_CONFIRMATION_ID}"
                )
                update = cast(
                    Update,
                    _Update(
                        message=_Message(),
                        effective_chat=_Chat(id=_CHAT_ID),
                        callback_query=query,
                    ),
                )

                await handle_callback_query(update, _context(service=service))

                assert service.confirm_calls == [
                    f"{_CONFIRMATION_ID}:telegram:{_CHAT_ID}:CONFIRM"
                ]
                assert "status=complete" in query.replies[-1]


            @pytest.mark.asyncio
            async def test_mode_switch_with_position_offers_guarded_flatten_transition() -> None:
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
                }
                assert (
                    "cb_operator_exit_flatten_switch_single_symbol" in callbacks
                )
                assert not service.request_calls

                query.data = "cb_operator_exit_flatten_switch_single_symbol"
                await handle_callback_query(
                    update,
                    _context(service=service, switcher=switcher),
                )

                assert service.request_calls == [
                    f"all:telegram:{_CHAT_ID}:single_symbol:True"
                ]
                confirmation_markup = query.reply_markups[-1]
                assert isinstance(confirmation_markup, InlineKeyboardMarkup)
                confirmation_callbacks = {
                    button.callback_data
                    for row in confirmation_markup.inline_keyboard
                    for button in row
                }
                assert f"cb_operator_exit_confirm_{_CONFIRMATION_ID}" in (
                    confirmation_callbacks
                )
            '''
        ),
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_operator_exit_telegram_ux.py <target-root>")
    root = Path(sys.argv[1]).resolve()
    if git(root, "rev-parse", "HEAD") != EXPECTED_HEAD:
        raise SystemExit("Unexpected feature HEAD; refusing stale UI patch")
    if git(root, "status", "--short"):
        raise SystemExit("Target working tree must be clean")

    patch_keyboards(root)
    patch_operator_commands(root)
    patch_commands(root)
    patch_callbacks(root)
    patch_context(root)
    patch_bot_commands(root)
    add_tests(root)
    print("Operator-exit Telegram UX patch applied")


if __name__ == "__main__":
    main()
