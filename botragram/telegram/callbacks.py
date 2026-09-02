"""
Botragram

Description:
    Telegram callback query handlers.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
import logging
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Final
from uuid import UUID

# =============================================================================
# Third-Party Imports
# =============================================================================
from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.ext import ContextTypes

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import (
    DEFAULT_PARSE_MODE,
    MENU_STATUS,
    OPERATOR_EXIT_STALE_CONFIRMATION_MESSAGE,
)
from botragram.enums import (
    ExchangeType,
    ExecutionPolicy,
    Interval,
    MarketType,
    StrategyType,
)
from botragram.exceptions import (
    ExecutionPolicySwitchBlockedError,
    OperatorExitConfirmationUnavailableError,
)
from botragram.models import LiveRuntimeHealthSnapshot, Order, Trade
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import (
    BOT_CONTEXT_KEY,
    MARKET_SEARCH_PENDING_KEY,
    BotContext,
    BotRuntimeControl,
)
from botragram.telegram.keyboards import (
    get_exchange_keyboard,
    get_execution_policy_confirmation_keyboard,
    get_execution_policy_keyboard,
    get_interval_keyboard,
    get_main_menu_keyboard,
    get_market_keyboard,
    get_market_search_keyboard,
    get_operator_exit_confirmation_keyboard,
    get_operator_flatten_switch_keyboard,
    get_risk_limits_keyboard,
    get_status_dashboard_keyboard,
    get_strategy_keyboard,
    get_stream_keyboard,
    get_tpsl_ratio_keyboard,
)
from botragram.telegram.messages import (
    get_exchange_message,
    get_execution_authorization_outcome_message,
    get_history_message,
    get_interval_message,
    get_market_message,
    get_market_search_prompt_message,
    get_orders_message,
    get_positions_message,
    get_resume_message,
    get_risk_limits_message,
    get_runtime_pause_message,
    get_settings_message,
    get_status_message,
    get_strategy_message,
    get_stream_message,
    get_tpsl_ratio_message,
)
from botragram.telegram.operator_exit_commands import (
    format_operator_exit_confirmation,
    format_operator_exit_snapshot,
    get_operator_exit_requester,
)

__all__ = [
    "handle_callback_query",
]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_EXCHANGE_CALLBACKS: Final[frozenset[str]] = frozenset(
    {
        "cb_exchange_bybit",
        "cb_exchange_binance",
        "cb_exchange_okx",
        "cb_exchange_bitget",
    }
)
_MARKET_CALLBACK_PREFIX: Final[str] = "cb_market_"
_MARKET_PAGE_CALLBACK_PREFIX: Final[str] = "cb_market_page_"
_INTERVAL_CALLBACK_PREFIX: Final[str] = "cb_interval_"
_STRATEGY_CALLBACK_PREFIX: Final[str] = "cb_strategy_"
_PRODUCT_CALLBACK_PREFIX: Final[str] = "cb_product_"
_OPPORTUNITY_APPROVE_CALLBACK_PREFIX: Final[str] = "cb_opportunity_approve_"
_OPPORTUNITY_REJECT_CALLBACK_PREFIX: Final[str] = "cb_opportunity_reject_"
_POLICY_SELECT_CALLBACK_PREFIX: Final[str] = "cb_policy_select_"
_POLICY_CONFIRM_CALLBACK_PREFIX: Final[str] = "cb_policy_confirm_"
_POLICY_CANCEL_CALLBACK: Final[str] = "cb_policy_cancel"
_OPERATOR_CLOSE_CALLBACK_PREFIX: Final[str] = "cb_operator_exit_close_"
_OPERATOR_CLOSE_ALL_CALLBACK: Final[str] = "cb_operator_exit_close_all"
_OPERATOR_CONFIRM_CALLBACK_PREFIX: Final[str] = "cb_operator_exit_confirm_"
_OPERATOR_CANCEL_CALLBACK_PREFIX: Final[str] = "cb_operator_exit_cancel_"
_OPERATOR_FLATTEN_SWITCH_PREFIX: Final[str] = "cb_operator_exit_flatten_switch_"


# =============================================================================
# Helpers
# =============================================================================
def _get_context(
    context: ContextTypes.DEFAULT_TYPE,
) -> BotContext:
    """Return the stored Botragram context or safe defaults."""
    bot_context = context.bot_data.get(BOT_CONTEXT_KEY)

    if isinstance(bot_context, BotContext):
        return bot_context

    return BotContext()


async def _has_open_positions(bot_context: BotContext) -> bool:
    """Fail safely when runtime configuration may affect an open position."""
    provider = bot_context.query_provider

    if provider is None:
        return True

    try:
        return bool(await provider.get_positions())
    except Exception:
        _LOGGER.exception("Runtime configuration position check failed")
        return True


async def _get_trading_symbols(bot_context: BotContext) -> tuple[str, ...] | None:
    """Return exchange-supported symbols and log transient lookup failures."""
    provider = bot_context.query_provider

    if provider is None:
        return None

    try:
        return tuple(await provider.get_trading_symbols())
    except Exception:
        _LOGGER.exception("Telegram market-symbol query failed")
        return None


async def _get_last_price(bot_context: BotContext) -> Decimal:
    """Return the provider's latest price without trusting stale context state."""
    provider = bot_context.query_provider

    if provider is None:
        return bot_context.last_price

    try:
        last_price = await provider.get_last_price()
    except Exception:
        _LOGGER.exception("Telegram market-price query failed")
        return bot_context.last_price

    bot_context.last_price = last_price
    return last_price


async def _resume_autonomous_live(bot_context: BotContext) -> bool:
    """Resume autonomous LIVE only from a reconciled fail-closed runtime state."""
    control = bot_context.runtime_control
    provider = bot_context.query_provider
    if control is None or provider is None:
        raise RuntimeError("Autonomous LIVE runtime observability is unavailable")

    recovery = await provider.get_autonomous_live_recovery()
    if recovery is None:
        raise RuntimeError("Autonomous LIVE recovery state is unavailable")
    if recovery.new_entry_blocked_by_recovery:
        raise RuntimeError("Autonomous LIVE recovery is incomplete")

    positions = tuple(await provider.get_positions())
    runtime_contexts = control.runtime_contexts
    managed_symbols = {runtime_context.symbol for runtime_context in runtime_contexts}
    position_symbols = {position.symbol for position in positions}

    if runtime_contexts:
        if managed_symbols != position_symbols:
            raise RuntimeError("LIVE portfolio requires reconciliation before resume")
        return control.resume()

    if positions:
        raise RuntimeError("Unmanaged LIVE positions require recovery before resume")
    if not recovery.autonomous_entry_authorized:
        raise RuntimeError("Autonomous LIVE entry is not authorized")

    return control.resume_global_cycle()


def _is_confirmed(
    control: BotRuntimeControl | None,
    requirement: str,
) -> bool:
    """Return whether Telegram explicitly confirmed one startup selection."""
    return (
        control is not None
        and requirement not in control.get_missing_configuration_requirements()
    )


def _get_exchange_markup(bot_context: BotContext) -> InlineKeyboardMarkup:
    """Return exchange buttons whose checks reflect confirmation state."""
    control = bot_context.runtime_control
    return get_exchange_keyboard(
        bot_context.exchange_type,
        bot_context.market_type,
        exchange_confirmed=_is_confirmed(control, "exchange"),
        market_type_confirmed=_is_confirmed(control, "market type"),
    )


def _get_exchange_configuration_message(bot_context: BotContext) -> str:
    """Return exchange text whose values reflect confirmation state."""
    control = bot_context.runtime_control
    return get_exchange_message(
        bot_context.exchange_type,
        bot_context.market_type,
        exchange_confirmed=_is_confirmed(control, "exchange"),
        market_type_confirmed=_is_confirmed(control, "market type"),
    )


def _get_authorization_identifier(
    *,
    callback_data: str,
    prefix: str,
) -> str | None:
    """Return a canonical opaque authorization ID from one callback payload."""
    identifier = callback_data.removeprefix(prefix).strip().lower()

    try:
        parsed_identifier = UUID(hex=identifier)
    except ValueError:
        return None

    return parsed_identifier.hex if parsed_identifier.hex == identifier else None


def _uses_multi_context_runtime(
    health: LiveRuntimeHealthSnapshot | None,
) -> bool:
    """Return whether legacy singular presentation values are unsafe to read."""
    return health is not None and len(health.contexts) > 1


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


def _is_single_symbol_configuration_callback(callback_data: str) -> bool:
    """Return whether an inline action belongs only to single-symbol setup."""
    return (
        callback_data in {"cb_exchange", "cb_market", "cb_interval"}
        or callback_data in _EXCHANGE_CALLBACKS
        or callback_data.startswith(_PRODUCT_CALLBACK_PREFIX)
        or callback_data.startswith(_MARKET_CALLBACK_PREFIX)
        or callback_data.startswith(_MARKET_PAGE_CALLBACK_PREFIX)
        or callback_data.startswith(_INTERVAL_CALLBACK_PREFIX)
        or callback_data.startswith("cb_stream_")
    )


async def _handle_execution_authorization_callback(
    *,
    query: CallbackQuery,
    bot_context: BotContext,
    callback_data: str,
) -> bool:
    """Handle a PAPER authorization callback through the application boundary."""
    if callback_data.startswith(_OPPORTUNITY_APPROVE_CALLBACK_PREFIX):
        prefix = _OPPORTUNITY_APPROVE_CALLBACK_PREFIX
        consume = "approve"
    elif callback_data.startswith(_OPPORTUNITY_REJECT_CALLBACK_PREFIX):
        prefix = _OPPORTUNITY_REJECT_CALLBACK_PREFIX
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


# =============================================================================
# Callback Handler
# =============================================================================
async def handle_callback_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle navigation and guarded runtime-configuration callbacks."""
    query = update.callback_query

    if query is None or not is_authorized_update(update=update, context=context):
        return

    await query.answer()
    data = query.data or ""
    bot_context = _get_context(context)

    if await _handle_execution_authorization_callback(
        query=query,
        bot_context=bot_context,
        callback_data=data,
    ):
        return

    service = bot_context.operator_exit_service
    requester = get_operator_exit_requester(update)

    if data == _OPERATOR_CLOSE_ALL_CALLBACK:
        if service is None or requester is None:
            await query.edit_message_text("Operator exit controls are unavailable.")
            return
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
        operator_symbol = (
            data.removeprefix(_OPERATOR_CLOSE_CALLBACK_PREFIX).strip().upper()
        )
        try:
            challenge = await service.request_close_position(
                symbol=operator_symbol,
                requested_by=requester,
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

    if data.startswith(_OPERATOR_CONFIRM_CALLBACK_PREFIX):
        if service is None or requester is None:
            await query.edit_message_text("Operator exit controls are unavailable.")
            return
        confirmation_id = (
            data.removeprefix(_OPERATOR_CONFIRM_CALLBACK_PREFIX).strip().lower()
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
        confirmation_id = (
            data.removeprefix(_OPERATOR_CANCEL_CALLBACK_PREFIX).strip().lower()
        )
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
            return
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
        return

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
        return

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
            return
        if target is bot_context.execution_policy:
            await query.edit_message_text(
                "ℹ️ <b>Trading mode tersebut sudah aktif.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_execution_policy_keyboard(
                    current_policy=bot_context.execution_policy,
                    available_policies=available,
                ),
            )
            return
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
        return

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
            return
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
                return
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return
        except Exception:
            _LOGGER.exception("Telegram execution-policy switch validation failed")
            await query.edit_message_text(
                "Trading-mode switch failed unexpectedly. No restart was "
                "scheduled. Reopen Trading Mode and try again.",
            )
            return
        if not changed:
            await query.edit_message_text(
                "ℹ️ <b>Trading mode tersebut sudah aktif.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return
        await query.edit_message_text(
            "🔄 <b>Trading session sedang direstart.</b>\n\n"
            f"Target: <code>{target.value}</code>\n"
            "Process Botragram tetap hidup. Session baru akan mulai dalam "
            "keadaan PAUSED.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        switcher.commit_execution_policy(execution_policy=target)
        return

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
        return

    if bot_context.is_discovery_workflow and _is_single_symbol_configuration_callback(
        data
    ):
        await query.edit_message_text(
            "ℹ️ <b>Single-symbol configuration tidak aktif pada discovery mode.</b>\n\n"
            "Pindah ke <b>Single Symbol</b> melalui Trading Mode untuk "
            "menggunakan kontrol ini.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    if data in {
        "cb_status",
        "cb_back_main",
        "cb_status_refresh",
        "cb_runtime_pause",
        "cb_runtime_resume",
    }:
        if data == "cb_runtime_pause" and bot_context.runtime_control is not None:
            changed = bot_context.runtime_control.pause()
            try:
                await query.answer("⏸️ Trading dijeda", show_alert=False)
            except Exception:
                pass
            if isinstance(query.message, Message):
                try:
                    await query.message.reply_text(
                        get_runtime_pause_message(changed=changed),
                        parse_mode=DEFAULT_PARSE_MODE,
                        reply_markup=get_main_menu_keyboard(
                            execution_policy=bot_context.execution_policy,
                            is_paused=True,
                        ),
                    )
                except Exception:
                    pass
        elif data == "cb_runtime_resume" and bot_context.runtime_control is not None:
            try:
                changed = (
                    await _resume_autonomous_live(bot_context)
                    if bot_context.is_autonomous_live
                    else bot_context.runtime_control.resume()
                )
                try:
                    await query.answer("▶️ Trading dilanjutkan", show_alert=False)
                except Exception:
                    pass
                if isinstance(query.message, Message):
                    try:
                        await query.message.reply_text(
                            get_resume_message(changed=changed),
                            parse_mode=DEFAULT_PARSE_MODE,
                            reply_markup=get_main_menu_keyboard(
                                execution_policy=bot_context.execution_policy,
                                is_paused=False,
                            ),
                        )
                    except Exception:
                        pass
            except RuntimeError as error:
                try:
                    await query.answer(f"⚠️ {error}", show_alert=True)
                except Exception:
                    pass
                if isinstance(query.message, Message):
                    try:
                        await query.message.reply_text(
                            "⚠️ <b>Trading belum dapat dilanjutkan.</b>\n"
                            f"<code>{escape(str(error))}</code>",
                            parse_mode=DEFAULT_PARSE_MODE,
                            reply_markup=get_main_menu_keyboard(
                                execution_policy=bot_context.execution_policy,
                                is_paused=True,
                            ),
                        )
                    except Exception:
                        pass
        elif data == "cb_status_refresh":
            try:
                await query.answer("🔄 Status diperbarui", show_alert=False)
            except Exception:
                pass

        last_price = bot_context.last_price
        available_balance: Decimal | None = None
        live_runtime_health: LiveRuntimeHealthSnapshot | None = None
        autonomous_live_recovery = None
        positions = bot_context.positions
        provider = bot_context.query_provider
        is_autonomous_live = bot_context.is_autonomous_live
        runtime_limits = (
            bot_context.runtime_risk_limit_service.get_snapshot()
            if bot_context.runtime_risk_limit_service is not None
            else None
        )

        if provider is not None:
            try:
                live_runtime_health = provider.get_live_runtime_health()
                autonomous_live_recovery = await provider.get_autonomous_live_recovery()
                positions = tuple(await provider.get_positions())
                available_balance = await provider.get_available_balance()
                if not is_autonomous_live and not _uses_multi_context_runtime(
                    live_runtime_health
                ):
                    last_price = await provider.get_last_price()
            except Exception:
                _LOGGER.exception("Telegram callback status query failed")

        is_multi_context_runtime = _uses_multi_context_runtime(live_runtime_health)
        runtime_control = bot_context.runtime_control
        symbol = (
            None
            if is_autonomous_live or is_multi_context_runtime
            else runtime_control.symbol
            if runtime_control is not None
            else bot_context.symbol
        )
        strategy_name = (
            bot_context.strategy_name
            if is_autonomous_live or is_multi_context_runtime
            else runtime_control.strategy_type.value
            if runtime_control is not None
            else bot_context.strategy_name
        )
        interval = (
            bot_context.configured_interval.value
            if is_autonomous_live
            else runtime_control.interval.value
            if runtime_control is not None and not is_multi_context_runtime
            else None
        )
        stream_active = (
            None
            if is_autonomous_live
            else runtime_control.stream_enabled
            if runtime_control is not None and not is_multi_context_runtime
            else None
        )
        missing_configuration_requirements = (
            ()
            if is_autonomous_live or is_multi_context_runtime
            else runtime_control.get_missing_configuration_requirements()
            if runtime_control is not None
            else ("exchange", "market type", "symbol", "interval", "strategy")
        )

        is_paused = (
            bot_context.runtime_control.is_paused
            if bot_context.runtime_control is not None
            else False
        )

        message = get_status_message(
            is_running=bot_context.is_running,
            trade_mode=bot_context.trade_mode,
            symbol=symbol,
            last_price=last_price,
            available_balance=available_balance,
            open_position_count=len(positions),
            is_paused=is_paused,
            exchange_type=bot_context.exchange_type,
            market_type=bot_context.market_type,
            strategy_name=strategy_name,
            interval=interval,
            stream_active=stream_active,
            total_unrealized_pnl=sum(
                (position.unrealized_pnl for position in positions),
                start=Decimal("0"),
            ),
            missing_configuration_requirements=missing_configuration_requirements,
            live_runtime_health=live_runtime_health,
            autonomous_live_recovery=autonomous_live_recovery,
            autonomous_live=is_autonomous_live,
            max_open_positions=(
                runtime_limits.max_open_positions
                if runtime_limits is not None
                else None
            ),
            position_protection_ready=(
                runtime_control.is_position_protection_ready
                if runtime_control is not None
                else None
            ),
        )
        dashboard_keyboard = get_status_dashboard_keyboard(
            is_paused=is_paused,
            has_positions=bool(positions),
            execution_policy=bot_context.execution_policy,
        )
        await query.edit_message_text(
            message,
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=dashboard_keyboard,
        )
    elif data == "cb_positions":
        positions = bot_context.positions

        if bot_context.query_provider is not None:
            try:
                positions = tuple(await bot_context.query_provider.get_positions())
            except Exception:
                _LOGGER.exception("Telegram callback positions query failed")

        pos_buttons: list[list[InlineKeyboardButton]] = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="cb_positions")],
            [InlineKeyboardButton(f"◀️ {MENU_STATUS}", callback_data="cb_status")],
        ]
        if positions:
            pos_buttons.insert(
                0,
                [
                    InlineKeyboardButton(
                        "⚠️ Close All Positions",
                        callback_data="cb_operator_exit_close_all",
                    )
                ],
            )
        await query.edit_message_text(
            get_positions_message(positions),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=InlineKeyboardMarkup(pos_buttons),
        )
    elif data == "cb_history":
        trades: tuple[Trade, ...] = ()
        if bot_context.query_provider is not None:
            try:
                trades = tuple(
                    await bot_context.query_provider.get_latest_trades(limit=10)
                )
            except Exception:
                _LOGGER.exception("Telegram callback history query failed")

        await query.edit_message_text(
            get_history_message(trades),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔄 Refresh", callback_data="cb_history")],
                    [
                        InlineKeyboardButton(
                            f"◀️ {MENU_STATUS}", callback_data="cb_status"
                        )
                    ],
                ]
            ),
        )
    elif data == "cb_orders":
        orders: tuple[Order, ...] = ()
        if bot_context.query_provider is not None:
            try:
                orders = tuple(
                    await bot_context.query_provider.get_latest_orders(limit=10)
                )
            except Exception:
                _LOGGER.exception("Telegram callback orders query failed")

        await query.edit_message_text(
            get_orders_message(orders),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔄 Refresh", callback_data="cb_orders")],
                    [
                        InlineKeyboardButton(
                            f"◀️ {MENU_STATUS}", callback_data="cb_status"
                        )
                    ],
                ]
            ),
        )
    elif (
        data == "cb_risk_limits"
        or data
        in {
            "cb_risk_pos_inc",
            "cb_risk_pos_dec",
            "cb_risk_size_inc",
            "cb_risk_size_dec",
        }
        or data.startswith("cb_risk_set_pos_")
        or data.startswith("cb_risk_set_size_")
    ):
        risk_limit_service = bot_context.runtime_risk_limit_service
        if risk_limit_service is None:
            await query.edit_message_text(
                "ℹ️ <b>Runtime risk limits tidak tersedia pada mode ini.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                f"◀️ {MENU_STATUS}", callback_data="cb_status"
                            )
                        ]
                    ]
                ),
            )
            return

        current_limits = risk_limit_service.get_snapshot()
        control = bot_context.runtime_control
        is_paused = control.is_paused if control is not None else False

        if data != "cb_risk_limits":
            if not is_paused:
                try:
                    await query.answer(
                        "⚠️ Pause trading terlebih dahulu sebelum mengubah risk limits!",
                        show_alert=True,
                    )
                except Exception:
                    pass
            else:
                new_pos = current_limits.max_open_positions
                new_size = current_limits.max_position_size_usdt
                ceil_pos = risk_limit_service.max_open_positions_ceiling
                ceil_size = risk_limit_service.max_position_size_usdt_ceiling

                if data == "cb_risk_pos_inc":
                    new_pos = min(new_pos + 1, ceil_pos)
                elif data == "cb_risk_pos_dec":
                    new_pos = max(new_pos - 1, 1)
                elif data == "cb_risk_size_inc":
                    new_size = min(new_size + Decimal("5"), ceil_size)
                elif data == "cb_risk_size_dec":
                    new_size = max(new_size - Decimal("5"), Decimal("5"))
                elif data.startswith("cb_risk_set_pos_"):
                    try:
                        val = int(data.removeprefix("cb_risk_set_pos_"))
                        new_pos = min(max(val, 1), ceil_pos)
                    except ValueError:
                        pass
                elif data.startswith("cb_risk_set_size_"):
                    try:
                        val_dec = Decimal(data.removeprefix("cb_risk_set_size_"))
                        new_size = min(max(val_dec, Decimal("5")), ceil_size)
                    except ValueError, InvalidOperation:
                        pass

                user = update.effective_user
                actor_id = user.id if user is not None else 0
                try:
                    current_limits = await risk_limit_service.update(
                        max_open_positions=new_pos,
                        max_position_size_usdt=new_size,
                        updated_by=f"telegram:{actor_id}",
                    )
                    try:
                        await query.answer(
                            f"✅ Limits: {new_pos} Pos | {new_size} USDT",
                            show_alert=False,
                        )
                    except Exception:
                        pass
                except (RuntimeError, ValueError) as error:
                    try:
                        await query.answer(f"⚠️ {error}", show_alert=True)
                    except Exception:
                        pass

        msg = get_risk_limits_message(
            limits=current_limits,
            max_open_positions_ceiling=risk_limit_service.max_open_positions_ceiling,
            max_position_size_usdt_ceiling=risk_limit_service.max_position_size_usdt_ceiling,
            is_paused=is_paused,
        )
        keyboard = get_risk_limits_keyboard(
            current_positions=current_limits.max_open_positions,
            current_size_usdt=current_limits.max_position_size_usdt,
            max_open_positions_ceiling=risk_limit_service.max_open_positions_ceiling,
            max_position_size_usdt_ceiling=risk_limit_service.max_position_size_usdt_ceiling,
        )
        await query.edit_message_text(
            msg,
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=keyboard,
        )
    elif data == "cb_tpsl_menu" or data.startswith("cb_tpsl_"):
        control = bot_context.runtime_control
        is_paused = control.is_paused if control is not None else False

        if data != "cb_tpsl_menu":
            if not is_paused:
                try:
                    await query.answer(
                        "⚠️ Pause trading terlebih dahulu sebelum mengubah TP/SL!",
                        show_alert=True,
                    )
                except Exception:
                    pass
            else:
                sl = bot_context.stop_loss_pct
                tp = bot_context.take_profit_pct

                if data == "cb_tpsl_sl_inc":
                    sl = min(sl + Decimal("0.001"), Decimal("0.10"))
                elif data == "cb_tpsl_sl_dec":
                    sl = max(sl - Decimal("0.001"), Decimal("0.001"))
                elif data == "cb_tpsl_tp_inc":
                    tp = min(tp + Decimal("0.002"), Decimal("0.20"))
                elif data == "cb_tpsl_tp_dec":
                    tp = max(tp - Decimal("0.002"), Decimal("0.002"))
                elif data == "cb_tpsl_rr_1.5":
                    tp = sl * Decimal("1.5")
                elif data == "cb_tpsl_rr_2.0":
                    tp = sl * Decimal("2.0")
                elif data == "cb_tpsl_rr_3.0":
                    tp = sl * Decimal("3.0")

                bot_context.stop_loss_pct = sl
                bot_context.take_profit_pct = tp

                try:
                    sl_pct = sl * Decimal("100")
                    tp_pct = tp * Decimal("100")
                    await query.answer(
                        f"✅ SL: {sl_pct:.2f}% | TP: {tp_pct:.2f}%",
                        show_alert=False,
                    )
                except Exception:
                    pass

        msg = get_tpsl_ratio_message(
            stop_loss_pct=bot_context.stop_loss_pct,
            take_profit_pct=bot_context.take_profit_pct,
            is_paused=is_paused,
        )
        keyboard = get_tpsl_ratio_keyboard(
            stop_loss_pct=bot_context.stop_loss_pct,
            take_profit_pct=bot_context.take_profit_pct,
        )
        await query.edit_message_text(
            msg,
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=keyboard,
        )
    elif data == "cb_config_menu":
        config_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🎯 Strategi", callback_data="cb_strategy"),
                    InlineKeyboardButton("⏱️ Interval", callback_data="cb_interval"),
                ],
                [
                    InlineKeyboardButton("🪙 Market", callback_data="cb_market"),
                    InlineKeyboardButton("🏢 Exchange", callback_data="cb_exchange"),
                ],
                [InlineKeyboardButton(f"◀️ {MENU_STATUS}", callback_data="cb_status")],
            ]
        )
        await query.edit_message_text(
            "⚙️ <b>Menu Konfigurasi Runtime</b>\n\n"
            "Pilih parameter runtime yang ingin Anda tinjau atau sesuaikan:",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=config_markup,
        )
    elif data == "cb_settings":
        await query.edit_message_text(
            get_settings_message(
                exchange_type=bot_context.exchange_type,
                strategy_name=(
                    bot_context.runtime_control.strategy_type.value
                    if bot_context.runtime_control is not None
                    else bot_context.strategy_name
                ),
                trade_mode=bot_context.trade_mode,
            ),
            parse_mode=DEFAULT_PARSE_MODE,
        )
    elif data == "cb_stop":
        await query.edit_message_text(
            "ℹ️ <b>Kontrol runtime belum tersedia melalui Telegram.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
    elif data == "cb_strategy":
        control = bot_context.runtime_control
        strategy_val = (
            control.strategy_type.value
            if control is not None
            else bot_context.strategy_name
        )
        confirmed = (
            _is_confirmed(control, "strategy")
            if not bot_context.is_autonomous_live
            else True
        )
        await query.edit_message_text(
            get_strategy_message(
                strategy_val,
                9,
                21,
                confirmed=confirmed,
            ),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_strategy_keyboard(
                strategy_val,
                confirmed=confirmed,
            ),
        )
    elif data == "cb_market":
        control = bot_context.runtime_control
        active_symbol = control.symbol if control is not None else bot_context.symbol
        symbols = await _get_trading_symbols(bot_context)
        if symbols is None:
            symbols = (active_symbol,)
        last_price = await _get_last_price(bot_context)
        confirmed = _is_confirmed(control, "symbol")
        await query.edit_message_text(
            get_market_message(
                active_symbol,
                last_price,
                confirmed=confirmed,
            ),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_market_keyboard(
                active_symbol,
                symbols,
                confirmed=confirmed,
            ),
        )
    elif data == "cb_interval":
        control = bot_context.runtime_control
        interval_val = (
            control.interval.value
            if control is not None
            else bot_context.configured_interval.value
        )
        confirmed = _is_confirmed(control, "interval")
        await query.edit_message_text(
            get_interval_message(
                interval_val,
                confirmed=confirmed,
            ),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_interval_keyboard(
                interval_val,
                confirmed=confirmed,
            ),
        )
    elif data == "cb_exchange":
        await query.edit_message_text(
            _get_exchange_configuration_message(bot_context),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=_get_exchange_markup(bot_context),
        )
    elif data in _EXCHANGE_CALLBACKS:
        control = bot_context.runtime_control
        raw_exchange = data.removeprefix("cb_exchange_")

        try:
            exchange_type = ExchangeType(raw_exchange)
        except ValueError:
            exchange_type = None

        if control is None or exchange_type is None:
            await query.edit_message_text(
                "⚠️ <b>Exchange tidak didukung.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=_get_exchange_markup(bot_context),
            )
            return

        try:
            changed = control.confirm_exchange(exchange_type)
        except RuntimeError as error:
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=_get_exchange_markup(bot_context),
            )
            return

        status = "dikonfirmasi" if changed else "sudah dikonfirmasi"
        await query.edit_message_text(
            _get_exchange_configuration_message(bot_context)
            + f"\n\nExchange {status} untuk sesi ini.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=_get_exchange_markup(bot_context),
        )
    elif data.startswith(_PRODUCT_CALLBACK_PREFIX):
        raw_market_type = data.removeprefix(_PRODUCT_CALLBACK_PREFIX)
        switcher = bot_context.market_type_switcher

        try:
            market_type = MarketType(raw_market_type)
        except ValueError:
            market_type = None

        if switcher is None or market_type is None:
            await query.edit_message_text(
                "⚠️ <b>Perpindahan Spot/Futures tidak tersedia.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=_get_exchange_markup(bot_context),
            )
            return

        try:
            changed = await switcher.prepare(market_type=market_type)
        except Exception as error:
            _LOGGER.exception("Telegram market-type switch validation failed")
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=_get_exchange_markup(bot_context),
            )
            return

        if not changed:
            await query.edit_message_text(
                _get_exchange_configuration_message(bot_context)
                + "\n\nProduct tersebut sudah aktif.",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=_get_exchange_markup(bot_context),
            )
            return

        await query.edit_message_text(
            "🔄 <b>Perpindahan connector dimulai.</b>\n\n"
            f"Target: <b>Binance {market_type.value.title()}</b>\n"
            "Botragram akan tersambung kembali secara otomatis.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        switcher.commit(market_type=market_type)
    elif data == "cb_market_noop":
        return
    elif data == "cb_market_search":
        chat_data = context.chat_data
        if chat_data is None:
            await query.edit_message_text(
                "⚠️ <b>Market search tidak tersedia untuk chat ini.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return

        chat_data[MARKET_SEARCH_PENDING_KEY] = True
        await query.edit_message_text(
            get_market_search_prompt_message(),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_market_search_keyboard(
                bot_context.symbol,
                (),
            ),
        )
    elif data.startswith(_MARKET_PAGE_CALLBACK_PREFIX):
        control = bot_context.runtime_control
        symbols = await _get_trading_symbols(bot_context)

        try:
            page = int(data.removeprefix(_MARKET_PAGE_CALLBACK_PREFIX))
        except ValueError:
            page = 0

        if control is None or symbols is None:
            await query.edit_message_text(
                "⚠️ <b>Daftar market sementara tidak tersedia.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return

        await query.edit_message_text(
            get_market_message(
                control.symbol,
                await _get_last_price(bot_context),
                confirmed=_is_confirmed(control, "symbol"),
            ),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_market_keyboard(
                control.symbol,
                symbols,
                page=page,
                confirmed=_is_confirmed(control, "symbol"),
            ),
        )
    elif data.startswith(_MARKET_CALLBACK_PREFIX):
        symbol = data.removeprefix(_MARKET_CALLBACK_PREFIX).upper()
        control = bot_context.runtime_control
        symbols = await _get_trading_symbols(bot_context)

        if control is None or symbols is None or symbol not in symbols:
            active_symbol = (
                control.symbol if control is not None else bot_context.symbol
            )
            await query.edit_message_text(
                "⚠️ <b>Market tidak didukung.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_market_keyboard(
                    active_symbol,
                    (active_symbol,),
                    confirmed=_is_confirmed(control, "symbol"),
                ),
            )
            return

        if symbol != control.symbol and await _has_open_positions(bot_context):
            await query.edit_message_text(
                "⚠️ <b>Tutup semua posisi sebelum mengganti market.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_market_keyboard(
                    control.symbol,
                    symbols,
                    confirmed=_is_confirmed(control, "symbol"),
                ),
            )
            return

        try:
            changed = control.select_symbol(symbol)
        except RuntimeError as error:
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_market_keyboard(
                    control.symbol,
                    symbols,
                    confirmed=_is_confirmed(control, "symbol"),
                ),
            )
            return

        bot_context.symbol = control.symbol
        status = "dipilih" if changed else "sudah aktif"
        try:
            await query.answer(f"Market {control.symbol} {status}", show_alert=False)
        except Exception:
            pass
        last_price = await _get_last_price(bot_context)
        await query.edit_message_text(
            get_market_message(
                control.symbol,
                last_price,
                confirmed=_is_confirmed(control, "symbol"),
            )
            + f"\n\n<b>{status.title()}</b> untuk siklus berikutnya.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_market_keyboard(
                control.symbol,
                symbols,
                confirmed=_is_confirmed(control, "symbol"),
            ),
        )
    elif data.startswith(_STRATEGY_CALLBACK_PREFIX):
        raw_strategy = data.removeprefix(_STRATEGY_CALLBACK_PREFIX)
        control = bot_context.runtime_control

        try:
            strategy_type = StrategyType(raw_strategy)
        except ValueError:
            await query.edit_message_text(
                "⚠️ <b>Strategy tidak didukung.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_strategy_keyboard(
                    bot_context.strategy_name,
                    confirmed=_is_confirmed(control, "strategy"),
                ),
            )
            return

        if control is None:
            await query.edit_message_text(
                "⚠️ <b>Runtime control tidak tersedia.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return

        if strategy_type is not control.strategy_type and await _has_open_positions(
            bot_context
        ):
            await query.edit_message_text(
                "⚠️ <b>Tutup semua posisi sebelum mengganti strategy.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_strategy_keyboard(
                    control.strategy_type.value,
                    confirmed=_is_confirmed(control, "strategy"),
                ),
            )
            return

        try:
            changed = control.select_strategy(strategy_type)
        except RuntimeError as error:
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_strategy_keyboard(
                    control.strategy_type.value,
                    confirmed=_is_confirmed(control, "strategy"),
                ),
            )
            return

        bot_context.strategy_name = control.strategy_type.value
        status = "dipilih" if changed else "sudah aktif"
        try:
            await query.answer(
                f"Strategy {strategy_type.value} {status}",
                show_alert=False,
            )
        except Exception:
            pass
        await query.edit_message_text(
            get_strategy_message(
                control.strategy_type.value,
                9,
                21,
                confirmed=_is_confirmed(control, "strategy"),
            )
            + f"\n\nStrategy {status} untuk siklus berikutnya.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_strategy_keyboard(
                control.strategy_type.value,
                confirmed=_is_confirmed(control, "strategy"),
            ),
        )
    elif data.startswith(_INTERVAL_CALLBACK_PREFIX):
        raw_interval = data.removeprefix(_INTERVAL_CALLBACK_PREFIX)
        control = bot_context.runtime_control

        try:
            interval = Interval(raw_interval)
        except ValueError:
            interval = None

        if control is None or interval is None:
            await query.edit_message_text(
                "⚠️ <b>Interval tidak didukung.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
            )
            return

        if interval is not control.interval and await _has_open_positions(bot_context):
            await query.edit_message_text(
                "⚠️ <b>Tutup semua posisi sebelum mengganti interval.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_interval_keyboard(
                    control.interval.value,
                    confirmed=_is_confirmed(control, "interval"),
                ),
            )
            return

        try:
            changed = control.select_interval(interval)
        except RuntimeError as error:
            await query.edit_message_text(
                f"⚠️ <b>{escape(str(error))}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_interval_keyboard(
                    control.interval.value,
                    confirmed=_is_confirmed(control, "interval"),
                ),
            )
            return

        status = "dipilih" if changed else "sudah aktif"
        try:
            await query.answer(
                f"Interval {interval.value} {status}",
                show_alert=False,
            )
        except Exception:
            pass
        await query.edit_message_text(
            get_interval_message(
                control.interval.value,
                confirmed=_is_confirmed(control, "interval"),
            )
            + f"\n\nInterval {status} untuk siklus berikutnya.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_interval_keyboard(
                control.interval.value,
                confirmed=_is_confirmed(control, "interval"),
            ),
        )
    elif data in {"cb_stream_start", "cb_stream_stop", "cb_stream_refresh"}:
        provider = bot_context.query_provider
        control = bot_context.runtime_control

        if provider is None:
            await query.edit_message_text(
                "⚠️ <b>Stream service tidak tersedia.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_stream_keyboard(),
            )
            return

        if data == "cb_stream_start" and control is not None:
            missing = control.get_missing_configuration_requirements()

            if missing:
                await query.edit_message_text(
                    "⚠️ <b>Lengkapi konfigurasi sebelum memulai stream:</b> "
                    + ", ".join(missing),
                    parse_mode=DEFAULT_PARSE_MODE,
                    reply_markup=get_stream_keyboard(),
                )
                return

            await provider.start_market_stream()
            await provider.wait_for_first_stream_tick()
        elif data == "cb_stream_stop":
            await provider.stop_market_stream()

        transport_connected = provider.is_stream_transport_connected()
        subscription_active = control.stream_enabled if control is not None else False
        first_tick_received = (
            subscription_active
            and control is not None
            and "first stream tick" not in control.get_missing_startup_requirements()
        )
        stream_last_price = (
            await _get_last_price(bot_context) if subscription_active else None
        )
        await query.edit_message_text(
            get_stream_message(
                transport_connected=transport_connected,
                subscription_active=subscription_active,
                first_tick_received=first_tick_received,
                last_price=stream_last_price,
            ),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_stream_keyboard(),
        )
