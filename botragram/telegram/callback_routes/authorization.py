"""
Botragram

Description:
    PAPER execution authorization callback handling.

Python:
    3.14+
"""

from __future__ import annotations

import logging
from typing import Final
from uuid import UUID

from telegram import CallbackQuery

from botragram.constants.telegram import DEFAULT_PARSE_MODE
from botragram.telegram.context import BotContext
from botragram.telegram.presentation.messages import (
    get_execution_authorization_outcome_message,
)

__all__ = ["handle_execution_authorization_callback"]

_LOGGER: Final[logging.Logger] = logging.getLogger("botragram.telegram.callbacks")
_APPROVE_PREFIX: Final[str] = "cb_opportunity_approve_"
_REJECT_PREFIX: Final[str] = "cb_opportunity_reject_"


def _get_authorization_identifier(*, callback_data: str, prefix: str) -> str | None:
    """Return a canonical opaque authorization ID from one callback payload."""
    identifier = callback_data.removeprefix(prefix).strip().lower()
    try:
        parsed_identifier = UUID(hex=identifier)
    except ValueError:
        return None
    return parsed_identifier.hex if parsed_identifier.hex == identifier else None


async def handle_execution_authorization_callback(
    *,
    query: CallbackQuery,
    bot_context: BotContext,
    callback_data: str,
) -> bool:
    """Handle a PAPER authorization callback through the application boundary."""
    if callback_data.startswith(_APPROVE_PREFIX):
        prefix = _APPROVE_PREFIX
        consume = "approve"
    elif callback_data.startswith(_REJECT_PREFIX):
        prefix = _REJECT_PREFIX
        consume = "reject"
    else:
        return False

    authorization_id = _get_authorization_identifier(
        callback_data=callback_data,
        prefix=prefix,
    )
    service = bot_context.execution_authorization_service

    if authorization_id is None:
        await query.edit_message_text(
            "<b>Opportunity Unavailable</b>\n\nInvalid authorization reference.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return True

    if service is None:
        await query.edit_message_text(
            "<b>Opportunity Unavailable</b>\n\nAuthorization service is unavailable.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return True

    try:
        outcome = (
            await service.approve(authorization_id=authorization_id)
            if consume == "approve"
            else await service.reject(authorization_id=authorization_id)
        )
    except Exception:
        _LOGGER.exception(
            "Telegram execution authorization callback failed: action=%s",
            consume,
        )
        await query.edit_message_text(
            "<b>Opportunity Processing Failed</b>\n\nPlease request a fresh "
            "opportunity.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return True

    await query.edit_message_text(
        get_execution_authorization_outcome_message(outcome),
        parse_mode=DEFAULT_PARSE_MODE,
    )
    return True
