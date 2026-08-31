"""Guarded flatten-and-strategy soft restart for Telegram operators."""

from __future__ import annotations

from html import escape
from typing import Protocol, runtime_checkable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from botragram.constants.telegram import (
    DEFAULT_PARSE_MODE,
    OPERATOR_EXIT_STALE_CONFIRMATION_MESSAGE,
)
from botragram.enums import OperatorExitStatus, StrategyType
from botragram.exceptions import (
    ExecutionPolicySwitchBlockedError,
    OperatorExitConfirmationUnavailableError,
)
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext
from botragram.telegram.operator_exit_commands import (
    format_operator_exit_confirmation,
    get_operator_exit_requester,
)

__all__ = [
    "strategy_flatten_confirm_callback",
    "strategy_flatten_request_callback",
]

_REQUEST_PREFIX = "cb_strategy_flatten_"
_CONFIRM_PREFIX = "cb_strategy_exit_confirm_"
_PENDING_TARGET_PREFIX = "strategy_exit_target:"


@runtime_checkable
class _StrategySessionSwitcher(Protocol):
    """Expose only the guarded strategy restart contract."""

    @property
    def current_strategy_type(self) -> StrategyType:
        """Return the strategy owned by the current session."""
        ...

    async def prepare_strategy(self, *, strategy_type: StrategyType) -> bool:
        """Validate and stage one safe strategy replacement."""
        ...

    def commit_strategy(self, *, strategy_type: StrategyType) -> None:
        """Commit an already-staged strategy replacement."""
        ...


def _get_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    """Return the active Telegram application context or safe defaults."""
    value = context.bot_data.get(BOT_CONTEXT_KEY)
    return value if isinstance(value, BotContext) else BotContext()


def _get_switcher(bot_context: BotContext) -> _StrategySessionSwitcher | None:
    """Return the strategy-aware runtime switcher when available."""
    switcher = bot_context.market_type_switcher
    return switcher if isinstance(switcher, _StrategySessionSwitcher) else None


def _target_key(confirmation_id: str) -> str:
    """Return one process-local key bound to the confirmation challenge."""
    return f"{_PENDING_TARGET_PREFIX}{confirmation_id}"


def _confirmation_keyboard(
    *,
    confirmation_id: str,
    requires_typed_confirmation: bool,
) -> InlineKeyboardMarkup:
    """Return strategy-aware confirmation controls without weakening MAINNET."""
    rows: list[list[InlineKeyboardButton]] = []
    if not requires_typed_confirmation:
        rows.append(
            [
                InlineKeyboardButton(
                    "✅ Confirm Exit & Apply Strategy",
                    callback_data=f"{_CONFIRM_PREFIX}{confirmation_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "Cancel",
                callback_data=f"cb_operator_exit_cancel_{confirmation_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


async def strategy_flatten_request_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Request an explicit Close All confirmation bound to a strategy target."""
    query = update.callback_query
    if query is None or not is_authorized_update(update=update, context=context):
        return
    await query.answer()

    raw_target = (query.data or "").removeprefix(_REQUEST_PREFIX)
    try:
        target = StrategyType(raw_target)
    except ValueError:
        await query.edit_message_text(
            "⚠️ <b>Strategy target tidak valid.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    bot_context = _get_context(context)
    service = bot_context.operator_exit_service
    switcher = _get_switcher(bot_context)
    requester = get_operator_exit_requester(update)
    if service is None or switcher is None or requester is None:
        await query.edit_message_text("Operator exit controls are unavailable.")
        return
    if target is switcher.current_strategy_type:
        await query.edit_message_text(
            "ℹ️ <b>Strategy target sudah aktif.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    try:
        challenge = await service.request_close_all(
            requested_by=requester,
            auto_pause=True,
        )
    except (RuntimeError, ValueError) as error:
        await query.edit_message_text(
            f"⚠️ <b>Close All tidak dapat dimulai.</b>\n\n{escape(str(error))}",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    context.bot_data[_target_key(challenge.confirmation_id)] = target.value
    message = (
        format_operator_exit_confirmation(challenge)
        + "\n"
        + f"target_strategy={target.value}\n"
        + (
            "MAINNET: setelah typed confirmation dan portfolio flat, pilih target "
            "strategy lagi agar tidak ada target process-local yang diasumsikan "
            "durable."
            if challenge.requires_typed_confirmation
            else "Setelah portfolio terbukti flat, target strategy akan diterapkan "
            "otomatis melalui soft restart."
        )
    )
    await query.edit_message_text(
        message,
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=_confirmation_keyboard(
            confirmation_id=challenge.confirmation_id,
            requires_typed_confirmation=challenge.requires_typed_confirmation,
        ),
    )


async def strategy_flatten_confirm_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Confirm flatten, then apply the bound strategy only after proven flatness."""
    query = update.callback_query
    if query is None or not is_authorized_update(update=update, context=context):
        return
    await query.answer()

    confirmation_id = (query.data or "").removeprefix(_CONFIRM_PREFIX).strip().lower()
    target_value = context.bot_data.get(_target_key(confirmation_id))
    try:
        target = StrategyType(target_value) if isinstance(target_value, str) else None
    except ValueError:
        target = None

    bot_context = _get_context(context)
    service = bot_context.operator_exit_service
    switcher = _get_switcher(bot_context)
    requester = get_operator_exit_requester(update)
    if service is None or switcher is None or requester is None or target is None:
        await query.edit_message_text(
            "⚠️ <b>Strategy target tidak lagi tersedia.</b>\n\n"
            "Tidak ada order baru yang akan dibuat dari callback ini. Periksa "
            "portfolio lalu pilih Strategy kembali.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    await query.edit_message_text(
        "⏳ <b>Close All & Strategy sedang diproses.</b>\n\n"
        f"Target: <code>{target.value}</code>\n"
        "Posisi ditutup satu per satu dan direkonsiliasi. Strategy hanya akan "
        "diterapkan setelah portfolio terbukti flat. Bot tetap <b>PAUSED</b>.",
        parse_mode=DEFAULT_PARSE_MODE,
    )

    try:
        snapshot = await service.confirm(
            confirmation_id=confirmation_id,
            requested_by=requester,
            token="CONFIRM",
        )
    except OperatorExitConfirmationUnavailableError:
        context.bot_data.pop(_target_key(confirmation_id), None)
        await query.edit_message_text(
            OPERATOR_EXIT_STALE_CONFIRMATION_MESSAGE,
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return
    except (RuntimeError, ValueError) as error:
        context.bot_data.pop(_target_key(confirmation_id), None)
        await query.edit_message_text(
            f"⚠️ <b>Operator exit ditolak.</b>\n\n{escape(str(error))}",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    if snapshot.status is not OperatorExitStatus.COMPLETE or snapshot.positions:
        context.bot_data.pop(_target_key(confirmation_id), None)
        remaining = (
            ", ".join(position.symbol for position in snapshot.positions) or "none"
        )
        reason = snapshot.failure_reason or "authoritative recovery masih berjalan"
        await query.edit_message_text(
            "⚠️ <b>Strategy belum diterapkan.</b>\n\n"
            f"Operator exit status: <code>{escape(snapshot.status.value)}</code>\n"
            f"Posisi saat ini: <code>{escape(remaining)}</code>\n"
            f"Alasan: <code>{escape(reason)}</code>\n\n"
            "Bot tetap PAUSED. Setelah recovery selesai dan portfolio flat, pilih "
            "Strategy kembali.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    try:
        changed = await switcher.prepare_strategy(strategy_type=target)
    except (ExecutionPolicySwitchBlockedError, RuntimeError, ValueError) as error:
        context.bot_data.pop(_target_key(confirmation_id), None)
        await query.edit_message_text(
            "⚠️ <b>Portfolio flat, tetapi strategy belum dapat diterapkan.</b>\n\n"
            f"{escape(str(error))}\n\nBot tetap PAUSED.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    context.bot_data.pop(_target_key(confirmation_id), None)
    if not changed:
        await query.edit_message_text(
            "✅ <b>Portfolio flat.</b>\n\nStrategy target sudah aktif. "
            "Bot tetap PAUSED.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    await query.edit_message_text(
        "🔄 <b>Portfolio flat. Strategy diterapkan.</b>\n\n"
        f"Target: <code>{target.value}</code>\n"
        "Soft restart sedang dimulai. Session baru tetap PAUSED sampai operator "
        "menekan Resume.",
        parse_mode=DEFAULT_PARSE_MODE,
    )
    switcher.commit_strategy(strategy_type=target)
