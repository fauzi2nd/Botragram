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
from typing import Final

# =============================================================================
# Third-Party Imports
# =============================================================================
from telegram import Update
from telegram.ext import ContextTypes

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import DEFAULT_PARSE_MODE, TELEGRAM_MARKET_SYMBOLS
from botragram.enums import ExchangeType, Interval, StrategyType
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext
from botragram.telegram.keyboards import (
    get_exchange_keyboard,
    get_interval_keyboard,
    get_market_keyboard,
    get_strategy_keyboard,
    get_stream_keyboard,
)
from botragram.telegram.messages import (
    get_exchange_message,
    get_interval_message,
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
_INTERVAL_CALLBACK_PREFIX: Final[str] = "cb_interval_"
_STRATEGY_CALLBACK_PREFIX: Final[str] = "cb_strategy_"
_SUPPORTED_MARKETS: Final[frozenset[str]] = frozenset(TELEGRAM_MARKET_SYMBOLS)


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

    if data in {"cb_status", "cb_back_main"}:
        last_price = bot_context.last_price
        available_balance = None
        positions = bot_context.positions
        provider = bot_context.query_provider

        if provider is not None:
            try:
                positions = tuple(await provider.get_positions())
                last_price = await provider.get_last_price()
                available_balance = await provider.get_available_balance()
            except Exception:
                _LOGGER.exception("Telegram callback status query failed")

        message = get_status_message(
            is_running=bot_context.is_running,
            trade_mode=bot_context.trade_mode,
            symbol=(
                bot_context.runtime_control.symbol
                if bot_context.runtime_control is not None
                else bot_context.symbol
            ),
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
            strategy_name=(
                bot_context.runtime_control.strategy_type.value
                if bot_context.runtime_control is not None
                else bot_context.strategy_name
            ),
            interval=(
                bot_context.runtime_control.interval.value
                if bot_context.runtime_control is not None
                else None
            ),
            stream_active=(
                bot_context.runtime_control.stream_enabled
                if bot_context.runtime_control is not None
                else None
            ),
            total_unrealized_pnl=sum(
                (position.unrealized_pnl for position in positions),
                start=Decimal("0"),
            ),
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
            get_exchange_message(
                bot_context.exchange_type,
                bot_context.market_type,
            ),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_exchange_keyboard(bot_context.exchange_type),
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
                reply_markup=get_exchange_keyboard(bot_context.exchange_type),
            )
            return

        try:
            changed = control.confirm_exchange(exchange_type)
        except RuntimeError as error:
            await query.edit_message_text(
                f"⚠️ <b>{error}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_exchange_keyboard(bot_context.exchange_type),
            )
            return

        status = "dikonfirmasi" if changed else "sudah dikonfirmasi"
        await query.edit_message_text(
            get_exchange_message(
                bot_context.exchange_type,
                bot_context.market_type,
            )
            + f"\n\nExchange {status} untuk sesi ini.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_exchange_keyboard(bot_context.exchange_type),
        )
    elif data.startswith(_MARKET_CALLBACK_PREFIX):
        symbol = data.removeprefix(_MARKET_CALLBACK_PREFIX).upper()
        control = bot_context.runtime_control

        if symbol not in _SUPPORTED_MARKETS or control is None:
            await query.edit_message_text(
                "⚠️ <b>Market tidak didukung.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_market_keyboard(bot_context.symbol),
            )
            return

        if symbol != control.symbol and await _has_open_positions(bot_context):
            await query.edit_message_text(
                "⚠️ <b>Tutup semua posisi sebelum mengganti market.</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_market_keyboard(control.symbol),
            )
            return

        try:
            changed = control.select_symbol(symbol)
        except RuntimeError as error:
            await query.edit_message_text(
                f"⚠️ <b>{error}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_market_keyboard(control.symbol),
            )
            return

        bot_context.symbol = control.symbol
        status = "dipilih" if changed else "sudah aktif"
        await query.edit_message_text(
            f"📈 <b>{control.symbol}</b> {status} untuk siklus berikutnya.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_market_keyboard(control.symbol),
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
                reply_markup=get_strategy_keyboard(bot_context.strategy_name),
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
                reply_markup=get_strategy_keyboard(control.strategy_type.value),
            )
            return

        try:
            changed = control.select_strategy(strategy_type)
        except RuntimeError as error:
            await query.edit_message_text(
                f"⚠️ <b>{error}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_strategy_keyboard(control.strategy_type.value),
            )
            return

        bot_context.strategy_name = control.strategy_type.value
        status = "dipilih" if changed else "sudah aktif"
        await query.edit_message_text(
            get_strategy_message(control.strategy_type.value, 9, 21)
            + f"\n\nStrategy {status} untuk siklus berikutnya.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_strategy_keyboard(control.strategy_type.value),
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
                reply_markup=get_interval_keyboard(control.interval.value),
            )
            return

        try:
            changed = control.select_interval(interval)
        except RuntimeError as error:
            await query.edit_message_text(
                f"⚠️ <b>{error}</b>",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=get_interval_keyboard(control.interval.value),
            )
            return

        status = "dipilih" if changed else "sudah aktif"
        await query.edit_message_text(
            get_interval_message(control.interval.value)
            + f"\n\nInterval {status} untuk siklus berikutnya.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_interval_keyboard(control.interval.value),
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
        elif data == "cb_stream_stop":
            await provider.stop_market_stream()

        transport_connected = provider.is_stream_transport_connected()
        subscription_active = control.stream_enabled if control is not None else False
        first_tick_received = (
            subscription_active
            and control is not None
            and "first stream tick" not in control.get_missing_startup_requirements()
        )
        await query.edit_message_text(
            get_stream_message(
                transport_connected=transport_connected,
                subscription_active=subscription_active,
                first_tick_received=first_tick_received,
            ),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_stream_keyboard(),
        )
