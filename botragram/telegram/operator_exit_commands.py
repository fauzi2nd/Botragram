"""Telegram operator controls for explicit portfolio exits."""

from __future__ import annotations

from typing import Final

from telegram import Update
from telegram.ext import ContextTypes

from botragram.constants.telegram import OPERATOR_EXIT_STALE_CONFIRMATION_MESSAGE
from botragram.enums import ExecutionPolicy
from botragram.exceptions import OperatorExitConfirmationUnavailableError
from botragram.models import OperatorExitConfirmation, OperatorExitSnapshot
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext
from botragram.telegram.keyboards import (
    get_operator_exit_confirmation_keyboard,
)

__all__ = [
    "cancel_exit_command",
    "close_all_and_switch_command",
    "close_all_command",
    "close_position_command",
    "confirm_exit_command",
    "exit_status_command",
    "format_operator_exit_confirmation",
    "format_operator_exit_snapshot",
    "get_operator_exit_requester",
]

_CLOSE_POSITION_USAGE: Final[str] = "/closeposition <symbol>"
_CLOSE_AND_SWITCH_USAGE: Final[str] = "/closeandswitch <execution_policy>"
_CONFIRM_USAGE: Final[str] = "/confirmexit <confirmation_id> <confirmation_token>"
_CANCEL_USAGE: Final[str] = "/cancelexit <confirmation_id>"


def _get_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    value = context.bot_data.get(BOT_CONTEXT_KEY)
    return value if isinstance(value, BotContext) else BotContext()


def get_operator_exit_requester(update: Update) -> str | None:
    """Return the chat-bound operator identity used by confirmations."""
    chat = update.effective_chat
    return f"telegram:{chat.id}" if chat is not None else None


def format_operator_exit_confirmation(
    challenge: OperatorExitConfirmation,
) -> str:
    symbols = ", ".join(challenge.symbols)
    target = (
        challenge.target_execution_policy.value
        if challenge.target_execution_policy is not None
        else "none"
    )
    return (
        "Operator exit awaiting explicit confirmation.\n"
        f"id={challenge.confirmation_id}\n"
        f"type={challenge.operation_type.value}\n"
        f"environment={challenge.environment}\n"
        f"symbols={symbols}\n"
        f"target_execution_policy={target}\n"
        f"expires_at={challenge.expires_at.isoformat()}\n"
        "No close order has been sent yet.\n"
        + (
            "MAINNET requires typed confirmation exactly with:\n"
            if challenge.requires_typed_confirmation
            else "Confirm with the button below or exactly with:\n"
        )
        + f"/confirmexit {challenge.confirmation_id} "
        f"{challenge.required_token}\n"
        + "Cancel with:\n"
        + f"/cancelexit {challenge.confirmation_id}"
    )


def format_operator_exit_snapshot(snapshot: OperatorExitSnapshot) -> str:
    positions = ", ".join(position.symbol for position in snapshot.positions) or "none"
    closing = ", ".join(snapshot.closing_symbols) or "none"
    target = (
        snapshot.target_execution_policy.value
        if snapshot.target_execution_policy is not None
        else "none"
    )
    lines = [
        "Operator exit control plane",
        f"status={snapshot.status.value}",
        f"trade_mode={snapshot.trade_mode.value}",
        f"environment={snapshot.exchange_environment.value}",
        f"positions={positions}",
        f"closing_symbols={closing}",
        f"target_execution_policy={target}",
    ]
    if snapshot.failure_reason is not None:
        lines.append(f"failure_reason={snapshot.failure_reason}")
    return "\n".join(lines)


async def exit_status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Display the authoritative operator-exit control-plane snapshot."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    service = _get_context(context).operator_exit_service
    if message is None:
        return
    if service is None:
        await message.reply_text("Operator exit controls are unavailable.")
        return
    try:
        snapshot = await service.get_snapshot()
    except RuntimeError as error:
        await message.reply_text(f"Operator exit status unavailable: {error}")
        return
    await message.reply_text(format_operator_exit_snapshot(snapshot))


async def close_position_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Request one explicit close-position confirmation and pause future entries."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    service = _get_context(context).operator_exit_service
    requester = get_operator_exit_requester(update)
    if message is None:
        return
    if service is None or requester is None:
        await message.reply_text("Operator exit controls are unavailable.")
        return
    args = context.args or []
    if len(args) != 1:
        await message.reply_text(f"Usage: {_CLOSE_POSITION_USAGE}")
        return
    try:
        challenge = await service.request_close_position(
            symbol=args[0],
            requested_by=requester,
            auto_pause=True,
        )
    except (RuntimeError, ValueError) as error:
        await message.reply_text(f"Close-position request rejected: {error}")
        return
    await message.reply_text(
        format_operator_exit_confirmation(challenge),
        reply_markup=get_operator_exit_confirmation_keyboard(
            confirmation=challenge,
        ),
    )


async def close_all_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Request one explicit whole-portfolio flatten confirmation."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    service = _get_context(context).operator_exit_service
    requester = get_operator_exit_requester(update)
    if message is None:
        return
    if service is None or requester is None:
        await message.reply_text("Operator exit controls are unavailable.")
        return
    if context.args:
        await message.reply_text("Usage: /closeall")
        return
    try:
        challenge = await service.request_close_all(
            requested_by=requester,
            auto_pause=True,
        )
    except (RuntimeError, ValueError) as error:
        await message.reply_text(f"Close-all request rejected: {error}")
        return
    await message.reply_text(
        format_operator_exit_confirmation(challenge),
        reply_markup=get_operator_exit_confirmation_keyboard(
            confirmation=challenge,
        ),
    )


async def close_all_and_switch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Request a flatten-and-switch confirmation inside the boot capability set."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    bot_context = _get_context(context)
    service = bot_context.operator_exit_service
    switcher = bot_context.market_type_switcher
    requester = get_operator_exit_requester(update)
    if message is None:
        return
    if service is None or switcher is None or requester is None:
        await message.reply_text("Operator exit controls are unavailable.")
        return
    args = context.args or []
    if len(args) != 1:
        await message.reply_text(f"Usage: {_CLOSE_AND_SWITCH_USAGE}")
        return
    try:
        target = ExecutionPolicy(args[0].strip().lower())
    except ValueError:
        values = ", ".join(policy.value for policy in ExecutionPolicy)
        await message.reply_text(f"Invalid execution policy. Allowed values: {values}")
        return
    if target is bot_context.execution_policy:
        await message.reply_text("Target execution policy is already active.")
        return
    if target not in switcher.available_execution_policies():
        await message.reply_text(
            "Target execution policy is outside this boot capability envelope."
        )
        return
    try:
        challenge = await service.request_close_all(
            requested_by=requester,
            target_execution_policy=target,
            auto_pause=True,
        )
    except (RuntimeError, ValueError) as error:
        await message.reply_text(f"Flatten-and-switch request rejected: {error}")
        return
    await message.reply_text(
        format_operator_exit_confirmation(challenge),
        reply_markup=get_operator_exit_confirmation_keyboard(
            confirmation=challenge,
        ),
    )


async def confirm_exit_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Consume one exact confirmation challenge and run its durable workflow."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    service = _get_context(context).operator_exit_service
    requester = get_operator_exit_requester(update)
    if message is None:
        return
    if service is None or requester is None:
        await message.reply_text("Operator exit controls are unavailable.")
        return
    args = context.args or []
    if len(args) < 2:
        await message.reply_text(f"Usage: {_CONFIRM_USAGE}")
        return
    confirmation_id = args[0]
    token = " ".join(args[1:])
    try:
        snapshot = await service.confirm(
            confirmation_id=confirmation_id,
            requested_by=requester,
            token=token,
        )
    except OperatorExitConfirmationUnavailableError:
        await message.reply_text(OPERATOR_EXIT_STALE_CONFIRMATION_MESSAGE)
        return
    except (RuntimeError, ValueError) as error:
        await message.reply_text(f"Operator exit confirmation rejected: {error}")
        return
    await message.reply_text(format_operator_exit_snapshot(snapshot))


async def cancel_exit_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Cancel one exact pending confirmation without submitting an order."""
    if not is_authorized_update(update=update, context=context):
        return
    message = update.effective_message
    service = _get_context(context).operator_exit_service
    requester = get_operator_exit_requester(update)
    if message is None:
        return
    if service is None or requester is None:
        await message.reply_text("Operator exit controls are unavailable.")
        return
    args = context.args or []
    if len(args) != 1:
        await message.reply_text(f"Usage: {_CANCEL_USAGE}")
        return
    try:
        await service.cancel_confirmation(
            confirmation_id=args[0],
            requested_by=requester,
        )
    except OperatorExitConfirmationUnavailableError:
        await message.reply_text(OPERATOR_EXIT_STALE_CONFIRMATION_MESSAGE)
        return
    except (RuntimeError, ValueError) as error:
        await message.reply_text(f"Operator exit cancellation rejected: {error}")
        return
    await message.reply_text(
        "Operator exit confirmation cancelled. No close order sent."
    )
