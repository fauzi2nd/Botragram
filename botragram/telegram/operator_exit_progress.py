"""Immediate Telegram progress feedback for confirmed operator exits."""

from __future__ import annotations

from html import escape

from telegram import Update
from telegram.ext import ContextTypes

from botragram.constants.telegram import (
    DEFAULT_PARSE_MODE,
    OPERATOR_EXIT_STALE_CONFIRMATION_MESSAGE,
)
from botragram.enums import OperatorExitStatus
from botragram.exceptions import OperatorExitConfirmationUnavailableError
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext
from botragram.telegram.operator_exit_commands import get_operator_exit_requester

__all__ = ["operator_exit_confirm_callback_with_progress"]

_CONFIRM_PREFIX = "cb_operator_exit_confirm_"


def _get_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    """Return the active Telegram application context or safe defaults."""
    candidate = context.bot_data.get(BOT_CONTEXT_KEY)
    return candidate if isinstance(candidate, BotContext) else BotContext()


async def operator_exit_confirm_callback_with_progress(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Acknowledge confirmation before awaiting durable portfolio mutation."""
    query = update.callback_query
    if query is None or not is_authorized_update(update=update, context=context):
        return

    await query.answer()
    confirmation_id = (query.data or "").removeprefix(_CONFIRM_PREFIX).strip().lower()
    service = _get_context(context).operator_exit_service
    requester = get_operator_exit_requester(update)
    if service is None or requester is None:
        await query.edit_message_text("Operator exit controls are unavailable.")
        return

    await query.edit_message_text(
        "⏳ <b>Operator Exit sedang diproses.</b>\n\n"
        "Konfirmasi diterima. Posisi akan ditutup satu per satu dan setiap hasil "
        "akan direkonsiliasi sebelum proses dilanjutkan.\n\n"
        "Bot tetap <b>PAUSED</b>. Jangan kirim konfirmasi berulang.",
        parse_mode=DEFAULT_PARSE_MODE,
    )

    try:
        snapshot = await service.confirm(
            confirmation_id=confirmation_id,
            requested_by=requester,
            token="CONFIRM",
        )
    except OperatorExitConfirmationUnavailableError:
        await query.edit_message_text(
            OPERATOR_EXIT_STALE_CONFIRMATION_MESSAGE,
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return
    except (RuntimeError, ValueError) as error:
        await query.edit_message_text(
            f"⚠️ <b>Operator exit ditolak.</b>\n\n{escape(str(error))}",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    remaining = ", ".join(position.symbol for position in snapshot.positions) or "none"
    if snapshot.status is OperatorExitStatus.COMPLETE:
        message = (
            "✅ <b>Operator Exit selesai.</b>\n\n"
            "Portfolio telah direkonsiliasi setelah penutupan.\n"
            f"Posisi tersisa: <code>{escape(remaining)}</code>"
        )
    elif snapshot.status is OperatorExitStatus.RECOVERY_REQUIRED:
        reason = snapshot.failure_reason or "authoritative recovery masih berjalan"
        message = (
            "⚠️ <b>Operator Exit masuk recovery.</b>\n\n"
            "Bot tetap PAUSED dan recovery durable akan melanjutkan tanpa blind "
            "resubmission.\n"
            f"Posisi saat ini: <code>{escape(remaining)}</code>\n"
            f"Alasan: <code>{escape(reason)}</code>"
        )
    elif snapshot.status is OperatorExitStatus.SWITCH_PENDING:
        message = (
            "🔄 <b>Portfolio sudah flat.</b>\n\n"
            "Perpindahan runtime sedang diserahkan ke soft-restart coordinator."
        )
    else:
        message = (
            "⏳ <b>Operator Exit masih diproses.</b>\n\n"
            f"Status: <code>{escape(snapshot.status.value)}</code>\n"
            f"Posisi saat ini: <code>{escape(remaining)}</code>"
        )

    await query.edit_message_text(message, parse_mode=DEFAULT_PARSE_MODE)
