"""
Botragram

Description:
    Guarded operator-exit Telegram callback workflow.

Python:
    3.14+
"""

from __future__ import annotations

from html import escape
from typing import Final

from telegram import CallbackQuery, Update

from botragram.constants.telegram import (
    DEFAULT_PARSE_MODE,
    OPERATOR_EXIT_STALE_CONFIRMATION_MESSAGE,
)
from botragram.enums import ExecutionPolicy
from botragram.exceptions import OperatorExitConfirmationUnavailableError
from botragram.telegram.command_handlers.operator_exit_commands import (
    format_operator_exit_confirmation,
    format_operator_exit_snapshot,
    get_operator_exit_requester,
)
from botragram.telegram.context import BotContext
from botragram.telegram.presentation.keyboards import (
    get_operator_exit_confirmation_keyboard,
)

__all__ = ["handle_operator_exit_callback"]

_CLOSE_PREFIX: Final[str] = "cb_operator_exit_close_"
_CLOSE_ALL: Final[str] = "cb_operator_exit_close_all"
_CONFIRM_PREFIX: Final[str] = "cb_operator_exit_confirm_"
_CANCEL_PREFIX: Final[str] = "cb_operator_exit_cancel_"
_FLATTEN_PREFIX: Final[str] = "cb_operator_exit_flatten_switch_"


async def handle_operator_exit_callback(
    *,
    update: Update,
    query: CallbackQuery,
    bot_context: BotContext,
    callback_data: str,
) -> bool:
    """Consume a guarded operator-exit action, if the payload matches."""
    if not (
        callback_data == _CLOSE_ALL
        or callback_data.startswith(
            (_CLOSE_PREFIX, _CONFIRM_PREFIX, _CANCEL_PREFIX, _FLATTEN_PREFIX)
        )
    ):
        return False

    service = bot_context.operator_exit_service
    requester = get_operator_exit_requester(update)
    if service is None or requester is None:
        await query.edit_message_text("Operator exit controls are unavailable.")
        return True

    if callback_data == _CLOSE_ALL:
        try:
            challenge = await service.request_close_all(
                requested_by=requester,
                auto_pause=True,
            )
        except (RuntimeError, ValueError) as error:
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return True
        await query.edit_message_text(
            format_operator_exit_confirmation(challenge),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_operator_exit_confirmation_keyboard(
                confirmation=challenge
            ),
        )
        return True

    if callback_data.startswith(_CLOSE_PREFIX):
        symbol = callback_data.removeprefix(_CLOSE_PREFIX).strip().upper()
        try:
            challenge = await service.request_close_position(
                symbol=symbol,
                requested_by=requester,
                auto_pause=True,
            )
        except (RuntimeError, ValueError) as error:
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return True
        await query.edit_message_text(
            format_operator_exit_confirmation(challenge),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_operator_exit_confirmation_keyboard(
                confirmation=challenge
            ),
        )
        return True

    if callback_data.startswith(_CONFIRM_PREFIX):
        confirmation_id = callback_data.removeprefix(_CONFIRM_PREFIX).strip().lower()
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
            return True
        except (RuntimeError, ValueError) as error:
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return True
        await query.edit_message_text(
            format_operator_exit_snapshot(snapshot),
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return True

    if callback_data.startswith(_CANCEL_PREFIX):
        confirmation_id = callback_data.removeprefix(_CANCEL_PREFIX).strip().lower()
        try:
            await service.cancel_confirmation(
                confirmation_id=confirmation_id,
                requested_by=requester,
            )
        except OperatorExitConfirmationUnavailableError:
            await query.edit_message_text(
                OPERATOR_EXIT_STALE_CONFIRMATION_MESSAGE,
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return True
        except (RuntimeError, ValueError) as error:
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return True
        await query.edit_message_text(
            "Operator exit confirmation cancelled. No close order sent."
        )
        return True

    target_value = callback_data.removeprefix(_FLATTEN_PREFIX)
    try:
        target = ExecutionPolicy(target_value)
    except ValueError:
        target = None
    if target is None:
        await query.edit_message_text("Invalid execution-policy target.")
        return True
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
        return True
    await query.edit_message_text(
        format_operator_exit_confirmation(challenge),
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=get_operator_exit_confirmation_keyboard(confirmation=challenge),
    )
    return True
