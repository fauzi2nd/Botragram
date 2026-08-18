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
from decimal import Decimal
from html import escape
from typing import Final
from uuid import UUID

# =============================================================================
# Third-Party Imports
# =============================================================================
from telegram import CallbackQuery, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import DEFAULT_PARSE_MODE
from botragram.enums import ExchangeType, Interval, MarketType, StrategyType
from botragram.models import LiveRuntimeHealthSnapshot
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import (
    BOT_CONTEXT_KEY,
    MARKET_SEARCH_PENDING_KEY,
    BotContext,
    BotRuntimeControl,
)
from botragram.telegram.keyboards import (
    get_exchange_keyboard,
    get_interval_keyboard,
    get_market_keyboard,
    get_market_search_keyboard,
    get_strategy_keyboard,
    get_stream_keyboard,
)
from botragram.telegram.messages import (
    get_exchange_message,
    get_execution_authorization_outcome_message,
    get_interval_message,
    get_market_message,
    get_market_search_prompt_message,
    get_positions_message,
    get_settings_message,
    get_status_message,
    get_strategy_message,
    get_stream_message,
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

    if data in {"cb_status", "cb_back_main"}:
        last_price = bot_context.last_price
        available_balance = None
        live_runtime_health = None
        positions = bot_context.positions
        provider = bot_context.query_provider

        if provider is not None:
            try:
                live_runtime_health = provider.get_live_runtime_health()
                positions = tuple(await provider.get_positions())
                available_balance = await provider.get_available_balance()
                if not _uses_multi_context_runtime(live_runtime_health):
                    last_price = await provider.get_last_price()
            except Exception:
                _LOGGER.exception("Telegram callback status query failed")

        is_multi_context_runtime = _uses_multi_context_runtime(live_runtime_health)
        runtime_control = bot_context.runtime_control
        symbol = (
            None
            if is_multi_context_runtime
            else runtime_control.symbol
            if runtime_control is not None
            else bot_context.symbol
        )
        strategy_name = (
            None
            if is_multi_context_runtime
            else runtime_control.strategy_type.value
            if runtime_control is not None
            else bot_context.strategy_name
        )
        interval = (
            runtime_control.interval.value
            if runtime_control is not None and not is_multi_context_runtime
            else None
        )
        stream_active = (
            runtime_control.stream_enabled
            if runtime_control is not None and not is_multi_context_runtime
            else None
        )
        missing_configuration_requirements = (
            ()
            if is_multi_context_runtime
            else runtime_control.get_missing_configuration_requirements()
            if runtime_control is not None
            else ("exchange", "market type", "symbol", "interval", "strategy")
        )

        message = get_status_message(
            is_running=bot_context.is_running,
            trade_mode=bot_context.trade_mode,
            symbol=symbol,
            last_price=last_price,
            available_balance=available_balance,
            open_position_count=len(positions),
            is_paused=(
                bot_context.runtime_control.is_paused
                if bot_context.runtime_control is not None
                else False
            ),
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
        )
        await query.edit_message_text(message, parse_mode=DEFAULT_PARSE_MODE)
    elif data == "cb_positions":
        positions = bot_context.positions

        if bot_context.query_provider is not None:
            try:
                positions = tuple(await bot_context.query_provider.get_positions())
            except Exception:
                _LOGGER.exception("Telegram callback positions query failed")

        await query.edit_message_text(
            get_positions_message(positions),
            parse_mode=DEFAULT_PARSE_MODE,
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
