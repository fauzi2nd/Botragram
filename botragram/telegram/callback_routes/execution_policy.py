"""
Botragram

Description:
    Guarded execution-policy switch callbacks.

Python:
    3.14+
"""

from __future__ import annotations

import logging
from html import escape
from typing import Final

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from botragram.constants.telegram import DEFAULT_PARSE_MODE, MENU_STATUS
from botragram.enums import ExecutionPolicy
from botragram.exceptions import ExecutionPolicySwitchBlockedError
from botragram.telegram.context import BotContext
from botragram.telegram.presentation.keyboards import (
    get_execution_policy_confirmation_keyboard,
    get_execution_policy_keyboard,
    get_operator_flatten_switch_keyboard,
)

__all__ = ["handle_execution_policy_callback"]

_LOGGER: Final[logging.Logger] = logging.getLogger("botragram.telegram.callbacks")
_POLICY_SELECT_CALLBACK_PREFIX: Final[str] = "cb_policy_select_"
_POLICY_CONFIRM_CALLBACK_PREFIX: Final[str] = "cb_policy_confirm_"
_POLICY_CANCEL_CALLBACK: Final[str] = "cb_policy_cancel"


def _parse_execution_policy_callback(
    *,
    callback_data: str,
    prefix: str,
) -> ExecutionPolicy | None:
    """Parse one exact execution-policy callback payload."""
    try:
        return ExecutionPolicy(callback_data.removeprefix(prefix))
    except ValueError:
        return None


async def handle_execution_policy_callback(
    *,
    query: CallbackQuery,
    bot_context: BotContext,
    data: str,
) -> bool:
    """Consume an execution-policy switch callback when its payload matches."""
    if data == "cb_policy_menu":
        switcher = bot_context.market_type_switcher
        available = (
            switcher.available_execution_policies() if switcher is not None else ()
        )
        await query.edit_message_text(
            "🔀 <b>Pilih Trading Mode / Execution Policy</b>\n\n"
            f"Mode aktif: <code>{bot_context.execution_policy.value}</code>",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_execution_policy_keyboard(
                current_policy=bot_context.execution_policy,
                available_policies=available,
            ),
        )
        return True

    if data == _POLICY_CANCEL_CALLBACK:
        await query.edit_message_text(
            "ℹ️ <b>Pemilihan mode ditutup.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"◀️ {MENU_STATUS}", callback_data="cb_status"
                        )
                    ],
                ]
            ),
        )
        return True

    if data.startswith(_POLICY_SELECT_CALLBACK_PREFIX):
        target = _parse_execution_policy_callback(
            callback_data=data,
            prefix=_POLICY_SELECT_CALLBACK_PREFIX,
        )
        switcher = bot_context.market_type_switcher
        available = (
            switcher.available_execution_policies() if switcher is not None else ()
        )
        if target is None or switcher is None or target not in available:
            await query.edit_message_text(
                "⚠️ <b>Trading mode tidak diizinkan oleh boot configuration.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return True
        if target is bot_context.execution_policy:
            await query.edit_message_text(
                "ℹ️ <b>Trading mode tersebut sudah aktif.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_execution_policy_keyboard(
                    current_policy=bot_context.execution_policy,
                    available_policies=available,
                ),
            )
            return True
        await query.edit_message_text(
            "🔄 <b>Switch Trading Mode</b>\n\n"
            f"<code>{bot_context.execution_policy.value}</code> → "
            f"<code>{target.value}</code>\n\n"
            "Syarat: runtime PAUSED, tidak ada posisi, tidak ada cycle aktif, "
            "dan untuk LIVE recovery/protection harus bersih.\n\n"
            "Trading session akan direbuild dalam process yang sama dan "
            "session baru tetap PAUSED.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_execution_policy_confirmation_keyboard(
                execution_policy=target,
            ),
        )
        return True

    if data.startswith(_POLICY_CONFIRM_CALLBACK_PREFIX):
        target = _parse_execution_policy_callback(
            callback_data=data,
            prefix=_POLICY_CONFIRM_CALLBACK_PREFIX,
        )
        switcher = bot_context.market_type_switcher
        if target is None or switcher is None:
            await query.edit_message_text(
                "⚠️ <b>Trading-mode switch tidak tersedia.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return True
        try:
            changed = await switcher.prepare_execution_policy(
                execution_policy=target,
            )
        except ExecutionPolicySwitchBlockedError as error:
            _LOGGER.info(
                "Telegram execution-policy switch blocked: target=%s reason=%s",
                target.value,
                error,
            )
            if (
                error.active_position_count > 0
                and bot_context.operator_exit_service is not None
            ):
                await query.edit_message_text(
                    f"⚠️ <b>{escape(str(error))}</b>\n\n"
                    f"{error.active_position_count} active position(s) block this "
                    "switch. "
                    "Botragram can flatten them through the guarded "
                    "operator-exit workflow and switch only after zero "
                    "exposure is verified.",
                    parse_mode=DEFAULT_PARSE_MODE,
                    reply_markup=get_operator_flatten_switch_keyboard(
                        execution_policy=target,
                    ),
                )
                return True
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return True
        except Exception:
            _LOGGER.exception("Telegram execution-policy switch validation failed")
            await query.edit_message_text(
                "Trading-mode switch failed unexpectedly. No restart was "
                "scheduled. Reopen Trading Mode and try again.",
            )
            return True
        if not changed:
            await query.edit_message_text(
                "ℹ️ <b>Trading mode tersebut sudah aktif.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return True
        await query.edit_message_text(
            "🔄 <b>Trading session sedang direstart.</b>\n\n"
            f"Target: <code>{target.value}</code>\n"
            "Process Botragram tetap hidup. Session baru akan mulai dalam "
            "keadaan PAUSED.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        switcher.commit_execution_policy(execution_policy=target)
        return True

    if data in {_POLICY_CANCEL_CALLBACK, "cb_policy_menu"}:
        switcher = bot_context.market_type_switcher
        available = (
            switcher.available_execution_policies()
            if switcher is not None
            else (bot_context.execution_policy,)
        )
        await query.edit_message_text(
            "🔄 <b>Trading Mode</b>\n\n"
            f"Current: <code>{bot_context.execution_policy.value}</code>",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_execution_policy_keyboard(
                current_policy=bot_context.execution_policy,
                available_policies=available,
            ),
        )
        return True

    return False
