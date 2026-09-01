"""
Botragram

Description:
    Telegram bot command handlers.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

import logging

# =============================================================================
# Standard Library
# =============================================================================
from decimal import Decimal
from html import escape
from typing import Final

# =============================================================================
# Third Party
# =============================================================================
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import (
    DEFAULT_PARSE_MODE,
    MENU_ACTIVITY,
    MENU_BALANCE,
    MENU_CONFIGURATION,
    MENU_DASHBOARD,
    MENU_EXCHANGE,
    MENU_HISTORY,
    MENU_HOME,
    MENU_INTERVAL,
    MENU_MARKET,
    MENU_MARKET_OVERVIEW,
    MENU_ORDERS,
    MENU_PAUSE,
    MENU_POSITIONS,
    MENU_RESUME,
    MENU_RISK_LIMITS,
    MENU_SETTINGS,
    MENU_START,
    MENU_STATUS,
    MENU_STOP,
    MENU_STRATEGY,
    MENU_STREAM,
    MENU_TEST,
    MENU_TRADING,
    MENU_TRADING_MODE,
)
from botragram.models import LiveRuntimeHealthSnapshot, Order, Trade
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import (
    BOT_CONTEXT_KEY,
    MARKET_SEARCH_PENDING_KEY,
    BotContext,
)
from botragram.telegram.keyboards import (
    get_activity_menu_keyboard,
    get_configuration_menu_keyboard,
    get_dashboard_menu_keyboard,
    get_exchange_keyboard,
    get_execution_policy_keyboard,
    get_interval_keyboard,
    get_main_menu_keyboard,
    get_market_keyboard,
    get_market_search_keyboard,
    get_operator_exit_positions_keyboard,
    get_status_dashboard_keyboard,
    get_strategy_keyboard,
    get_stream_keyboard,
    get_trading_menu_keyboard,
)
from botragram.telegram.messages import (
    get_balance_message,
    get_exchange_message,
    get_history_message,
    get_interval_message,
    get_market_message,
    get_market_overview_message,
    get_market_search_results_message,
    get_navigation_message,
    get_orders_message,
    get_positions_message,
    get_resume_message,
    get_runtime_pause_message,
    get_settings_message,
    get_startup_configuration_message,
    get_status_message,
    get_strategy_message,
    get_stream_message,
    get_test_message,
    get_welcome_message,
)
from botragram.telegram.risk_limit_commands import risk_limits_command

logger: Final[logging.Logger] = logging.getLogger(__name__)
_HISTORY_LIMIT: Final[int] = 10
_ORDER_LIMIT: Final[int] = 10
_MARKET_SEARCH_RESULT_LIMIT: Final[int] = 10
_MENU_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        MENU_ACTIVITY,
        MENU_BALANCE,
        MENU_CONFIGURATION,
        MENU_DASHBOARD,
        MENU_EXCHANGE,
        MENU_HISTORY,
        MENU_HOME,
        MENU_INTERVAL,
        MENU_MARKET,
        MENU_MARKET_OVERVIEW,
        MENU_ORDERS,
        MENU_PAUSE,
        MENU_POSITIONS,
        MENU_RESUME,
        MENU_RISK_LIMITS,
        MENU_SETTINGS,
        MENU_START,
        MENU_STATUS,
        MENU_STOP,
        MENU_STRATEGY,
        MENU_STREAM,
        MENU_TEST,
        MENU_TRADING,
        MENU_TRADING_MODE,
    }
)
_DATA_UNAVAILABLE_MESSAGE: Final[str] = (
    "⚠️ <b>Data sementara tidak tersedia.</b> Silakan coba lagi."
)


def _get_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    """Retrieve BotContext from Telegram bot_data.

    Args:
        context: Telegram callback context.

    Returns:
        BotContext instance, or a fresh default if not set.
    """
    ctx = context.bot_data.get(BOT_CONTEXT_KEY)
    if isinstance(ctx, BotContext):
        return ctx
    return BotContext()


def _get_runtime_symbol(context: BotContext) -> str:
    """Return the actively selected runtime symbol."""
    control = context.runtime_control
    return control.symbol if control is not None else context.symbol


def _get_runtime_strategy(context: BotContext) -> str:
    """Return the actively selected runtime strategy name."""
    control = context.runtime_control
    return control.strategy_type.value if control is not None else context.strategy_name


def _uses_multi_context_runtime(
    health: LiveRuntimeHealthSnapshot | None,
) -> bool:
    """Return whether legacy singular presentation values are unsafe to read."""
    return health is not None and len(health.contexts) > 1


def _is_runtime_confirmed(context: BotContext, requirement: str) -> bool:
    """Return whether Telegram confirmed one runtime selection."""
    control = context.runtime_control
    return (
        control is not None
        and requirement not in control.get_missing_configuration_requirements()
    )


def _get_missing_configuration_requirements(context: BotContext) -> tuple[str, ...]:
    """Return unconfirmed Telegram configuration fields."""
    control = context.runtime_control
    if control is None:
        return ("exchange", "market type", "symbol", "interval", "strategy")

    return control.get_missing_configuration_requirements()


def _get_startup_configuration_message(context: BotContext) -> str:
    """Return the current startup checklist for Telegram."""
    control = context.runtime_control

    if control is None:
        return ""

    return get_startup_configuration_message(
        exchange=context.exchange_type,
        market_type=control.market_type.value,
        symbol=control.symbol,
        interval=control.interval.value,
        strategy=control.strategy_type.value,
        missing_requirements=control.get_missing_startup_requirements(),
    )


async def _resume_autonomous_live(context: BotContext) -> bool:
    """Resume autonomous LIVE only from a reconciled fail-closed runtime state."""
    control = context.runtime_control
    provider = context.query_provider
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


def _get_context_main_menu_keyboard(context: BotContext) -> ReplyKeyboardMarkup:
    """Return a persistent keyboard that cannot mix incompatible workflows."""
    control = context.runtime_control
    return get_main_menu_keyboard(
        execution_policy=context.execution_policy,
        is_paused=control.is_paused if control is not None else True,
    )


async def _reject_discovery_managed_configuration(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Reject single-symbol configuration controls in discovery workflows."""
    bot_context = _get_context(context)
    if not bot_context.is_discovery_workflow:
        return False
    if update.message is not None:
        await update.message.reply_text(
            "ℹ️ <b>Konfigurasi market dikelola oleh discovery workflow.</b>\n\n"
            "Gunakan <b>Trading Mode</b> dan pindah ke <b>Single Symbol</b> "
            "untuk memilih exchange product, symbol, strategy, interval, atau stream.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=_get_context_main_menu_keyboard(bot_context),
        )
    return True


async def _reply_data_unavailable(update: Update) -> None:
    """Return a truthful transient query failure response."""
    if update.message is not None:
        await update.message.reply_text(
            _DATA_UNAVAILABLE_MESSAGE,
            parse_mode=DEFAULT_PARSE_MODE,
        )


async def _reply_market_search_results(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    keyword: str,
) -> None:
    """Search exchange symbols and return compact selectable results."""
    if update.message is None:
        return

    normalized_keyword = keyword.strip().upper()
    if not normalized_keyword or not normalized_keyword.isalnum():
        await update.message.reply_text(
            "⚠️ <b>Gunakan huruf dan angka saja.</b> Contoh: BTC atau BTCUSDT.",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    bot_context = _get_context(context)
    provider = bot_context.query_provider
    if provider is None:
        await _reply_data_unavailable(update)
        return

    try:
        symbols = tuple(await provider.get_trading_symbols())
    except Exception:
        logger.exception("Telegram market search failed")
        await _reply_data_unavailable(update)
        return

    all_matches = tuple(
        sorted(
            (symbol for symbol in symbols if normalized_keyword in symbol.upper()),
            key=lambda symbol: (
                not symbol.upper().startswith(normalized_keyword),
                len(symbol),
                symbol,
            ),
        )
    )
    results = all_matches[:_MARKET_SEARCH_RESULT_LIMIT]
    await update.message.reply_text(
        get_market_search_results_message(
            keyword=normalized_keyword,
            result_count=len(results),
            total_matches=len(all_matches),
        ),
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=get_market_search_keyboard(
            _get_runtime_symbol(bot_context),
            results,
            confirmed=_is_runtime_confirmed(bot_context, "symbol"),
        ),
    )


async def _show_navigation(
    *,
    update: Update,
    title: str,
    description: str,
    keyboard: ReplyKeyboardMarkup,
) -> None:
    """Switch the persistent keyboard to one compact navigation level."""
    if update.message is None:
        return

    await update.message.reply_text(
        get_navigation_message(title=title, description=description),
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=keyboard,
    )


# =============================================================================
# Command Handlers
# =============================================================================
async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /start command.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        checklist = (
            "" if ctx.is_discovery_workflow else _get_startup_configuration_message(ctx)
        )
        msg = get_welcome_message()

        if checklist:
            msg = f"{msg}\n\n{checklist}"
        kb = _get_context_main_menu_keyboard(ctx)
        await update.message.reply_text(
            msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=kb
        )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /status command.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        last_price = ctx.last_price
        available_balance: Decimal | None = None
        live_runtime_health = None
        autonomous_live_recovery = None
        positions = ctx.positions
        provider = ctx.query_provider
        is_autonomous_live = ctx.is_autonomous_live
        runtime_limits = (
            ctx.runtime_risk_limit_service.get_snapshot()
            if ctx.runtime_risk_limit_service is not None
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
                logger.exception("Telegram status query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_status_message(
            is_running=ctx.is_running,
            trade_mode=ctx.trade_mode,
            symbol=(
                None
                if is_autonomous_live
                or _uses_multi_context_runtime(live_runtime_health)
                else _get_runtime_symbol(ctx)
            ),
            last_price=last_price,
            available_balance=available_balance,
            open_position_count=len(positions),
            is_paused=(
                ctx.runtime_control.is_paused
                if ctx.runtime_control is not None
                else False
            ),
            exchange_type=ctx.exchange_type,
            market_type=ctx.market_type,
            strategy_name=(
                ctx.strategy_name
                if is_autonomous_live
                or _uses_multi_context_runtime(live_runtime_health)
                else _get_runtime_strategy(ctx)
            ),
            interval=(
                ctx.configured_interval.value
                if is_autonomous_live
                else ctx.runtime_control.interval.value
                if ctx.runtime_control is not None
                and not _uses_multi_context_runtime(live_runtime_health)
                else None
            ),
            stream_active=(
                None
                if is_autonomous_live
                else ctx.runtime_control.stream_enabled
                if ctx.runtime_control is not None
                and not _uses_multi_context_runtime(live_runtime_health)
                else None
            ),
            total_unrealized_pnl=sum(
                (position.unrealized_pnl for position in positions),
                start=Decimal("0"),
            ),
            missing_configuration_requirements=(
                ()
                if is_autonomous_live
                or _uses_multi_context_runtime(live_runtime_health)
                else _get_missing_configuration_requirements(ctx)
            ),
            live_runtime_health=live_runtime_health,
            autonomous_live_recovery=autonomous_live_recovery,
            autonomous_live=is_autonomous_live,
            max_open_positions=(
                runtime_limits.max_open_positions
                if runtime_limits is not None
                else None
            ),
            position_protection_ready=(
                ctx.runtime_control.is_position_protection_ready
                if ctx.runtime_control is not None
                else None
            ),
        )
        is_paused = (
            ctx.runtime_control.is_paused if ctx.runtime_control is not None else False
        )
        await update.message.reply_text(
            msg,
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_status_dashboard_keyboard(
                is_paused=is_paused,
                has_positions=bool(positions),
                execution_policy=ctx.execution_policy,
            ),
        )


async def positions_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /positions command.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        positions = ctx.positions

        if ctx.query_provider is not None:
            try:
                positions = tuple(await ctx.query_provider.get_positions())
            except Exception:
                logger.exception("Telegram positions query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_positions_message(positions)
        exit_markup = (
            get_operator_exit_positions_keyboard(positions=positions)
            if ctx.operator_exit_service is not None and positions
            else None
        )
        await update.message.reply_text(
            msg,
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=exit_markup,
        )


async def settings_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /settings command.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        msg = get_settings_message(
            exchange_type=ctx.exchange_type,
            strategy_name=_get_runtime_strategy(ctx),
            trade_mode=ctx.trade_mode,
        )
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def exchange_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /exchange command — show exchange selection keyboard.

    Args:
        update: Telegram update object.
        context: Callback context object.
    """
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return
        if await _reject_discovery_managed_configuration(
            update=update,
            context=context,
        ):
            return

        ctx = _get_context(context)
        exchange_confirmed = _is_runtime_confirmed(ctx, "exchange")
        market_type_confirmed = _is_runtime_confirmed(ctx, "market type")
        msg = get_exchange_message(
            ctx.exchange_type,
            ctx.market_type,
            exchange_confirmed=exchange_confirmed,
            market_type_confirmed=market_type_confirmed,
        )
        kb = get_exchange_keyboard(
            ctx.exchange_type,
            ctx.market_type,
            exchange_confirmed=exchange_confirmed,
            market_type_confirmed=market_type_confirmed,
        )
        await update.message.reply_text(
            msg, parse_mode=DEFAULT_PARSE_MODE, reply_markup=kb
        )


async def market_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return
        if await _reject_discovery_managed_configuration(
            update=update,
            context=context,
        ):
            return

        ctx = _get_context(context)
        last_price = ctx.last_price
        symbols: tuple[str, ...]

        if ctx.query_provider is not None:
            try:
                last_price = await ctx.query_provider.get_last_price()
                symbols = tuple(await ctx.query_provider.get_trading_symbols())
            except Exception:
                logger.exception("Telegram market query failed")
                await _reply_data_unavailable(update)
                return
        else:
            await _reply_data_unavailable(update)
            return

        symbol = _get_runtime_symbol(ctx)
        ctx.last_price = last_price
        msg = get_market_message(
            symbol,
            last_price,
            confirmed=_is_runtime_confirmed(ctx, "symbol"),
        )
        await update.message.reply_text(
            msg,
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_market_keyboard(
                symbol,
                symbols,
                confirmed=_is_runtime_confirmed(ctx, "symbol"),
            ),
        )


async def market_overview_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Show read-only market data without configuration controls."""
    if update.message is None:
        return
    if not is_authorized_update(update=update, context=context):
        return

    bot_context = _get_context(context)
    symbol = _get_runtime_symbol(bot_context)
    confirmed = _is_runtime_confirmed(bot_context, "symbol")
    last_price = bot_context.last_price
    provider = bot_context.query_provider

    if provider is not None and confirmed:
        try:
            last_price = await provider.get_last_price()
        except Exception:
            logger.exception("Telegram market overview query failed")
            await _reply_data_unavailable(update)
            return

    await update.message.reply_text(
        get_market_overview_message(
            symbol=symbol,
            last_price=last_price,
            confirmed=confirmed,
        ),
        parse_mode=DEFAULT_PARSE_MODE,
    )


async def orders_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        orders: tuple[Order, ...] = ()

        if ctx.query_provider is not None:
            try:
                orders = tuple(
                    await ctx.query_provider.get_latest_orders(limit=_ORDER_LIMIT)
                )
            except Exception:
                logger.exception("Telegram orders query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_orders_message(orders)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        balance = Decimal("0")

        if ctx.query_provider is not None:
            try:
                balance = await ctx.query_provider.get_available_balance()
            except Exception:
                logger.exception("Telegram balance query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_balance_message(balance)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def history_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        trades: tuple[Trade, ...] = ()

        if ctx.query_provider is not None:
            try:
                trades = tuple(
                    await ctx.query_provider.get_latest_trades(limit=_HISTORY_LIMIT)
                )
            except Exception:
                logger.exception("Telegram history query failed")
                await _reply_data_unavailable(update)
                return

        msg = get_history_message(trades)
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def strategy_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        fast_period = 9
        slow_period = 21
        strategy_name = _get_runtime_strategy(ctx)
        confirmed = (
            _is_runtime_confirmed(ctx, "strategy")
            if not ctx.is_autonomous_live
            else True
        )
        msg = get_strategy_message(
            strategy_name,
            fast_period,
            slow_period,
            confirmed=confirmed,
        )
        await update.message.reply_text(
            msg,
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_strategy_keyboard(
                strategy_name,
                confirmed=confirmed,
            ),
        )


async def interval_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Show the runtime candle-interval selector."""
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return
        if await _reject_discovery_managed_configuration(
            update=update,
            context=context,
        ):
            return

        ctx = _get_context(context)
        control = ctx.runtime_control

        if control is None:
            await _reply_data_unavailable(update)
            return

        await update.message.reply_text(
            get_interval_message(
                control.interval.value,
                confirmed=_is_runtime_confirmed(ctx, "interval"),
            ),
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_interval_keyboard(
                control.interval.value,
                confirmed=_is_runtime_confirmed(ctx, "interval"),
            ),
        )


async def stream_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return
        if await _reject_discovery_managed_configuration(
            update=update,
            context=context,
        ):
            return

        ctx = _get_context(context)
        provider = ctx.query_provider
        transport_connected = (
            provider.is_stream_transport_connected() if provider is not None else False
        )
        subscription_active = (
            ctx.runtime_control.stream_enabled
            if ctx.runtime_control is not None
            else False
        )
        first_tick_received = False
        last_price: Decimal | None = None

        if ctx.runtime_control is not None and subscription_active:
            first_tick_received = (
                "first stream tick"
                not in ctx.runtime_control.get_missing_startup_requirements()
            )
            if provider is not None:
                try:
                    last_price = await provider.get_last_price()
                except Exception:
                    logger.exception("Telegram stream price query failed")
        msg = get_stream_message(
            transport_connected=transport_connected,
            subscription_active=subscription_active,
            first_tick_received=first_tick_received,
            last_price=last_price,
        )
        await update.message.reply_text(
            msg,
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_stream_keyboard(),
        )


async def start_bot_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        control = ctx.runtime_control

        if control is None:
            await _reply_data_unavailable(update)
            return

        try:
            changed = (
                await _resume_autonomous_live(ctx)
                if ctx.is_autonomous_live
                else control.resume()
            )
            msg = get_resume_message(changed=changed)
        except RuntimeError as error:
            if ctx.is_autonomous_live:
                msg = (
                    "⚠️ <b>Autonomous LIVE belum dapat dilanjutkan.</b>\n"
                    f"<code>{escape(str(error))}</code>"
                )
            else:
                checklist = _get_startup_configuration_message(ctx)
                msg = f"⚠️ <b>Trading belum dapat dimulai.</b>\n\n{checklist}"
        except Exception:
            logger.exception("Autonomous LIVE resume verification failed")
            msg = (
                "⚠️ <b>Autonomous LIVE belum dapat dilanjutkan.</b> "
                "Runtime state tidak tersedia."
            )
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def pause_bot_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        ctx = _get_context(context)
        control = ctx.runtime_control

        if control is None:
            await _reply_data_unavailable(update)
            return

        msg = get_runtime_pause_message(changed=control.pause())
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def trading_mode_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Show workflows allowed inside the immutable boot capability envelope."""
    if update.message is None:
        return
    if not is_authorized_update(update=update, context=context):
        return

    bot_context = _get_context(context)
    switcher = bot_context.market_type_switcher
    available = (
        switcher.available_execution_policies()
        if switcher is not None
        else (bot_context.execution_policy,)
    )
    await update.message.reply_text(
        "🔄 <b>Trading Mode</b>\n\n"
        f"Current: <code>{bot_context.execution_policy.value}</code>\n\n"
        "Pergantian mode hanya mengganti trading session dalam process yang sama. "
        "Trade mode, network, credential, dan MAINNET authorization tidak berubah.",
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=get_execution_policy_keyboard(
            current_policy=bot_context.execution_policy,
            available_policies=available,
        ),
    )


async def test_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        if not is_authorized_update(update=update, context=context):
            return

        msg = get_test_message()
        await update.message.reply_text(msg, parse_mode=DEFAULT_PARSE_MODE)


async def menu_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle a selection from the persistent Telegram reply keyboard.

    Args:
        update: Incoming Telegram update.
        context: Telegram handler context.
    """
    if update.message is None:
        return

    if not is_authorized_update(update=update, context=context):
        return

    action = update.message.text or ""
    bot_context = _get_context(context)
    chat_data = context.chat_data
    search_pending = bool(
        chat_data is not None and chat_data.get(MARKET_SEARCH_PENDING_KEY) is True
    )
    if search_pending:
        is_menu_action = action in _MENU_ACTIONS
        is_valid_keyword = bool(action.strip()) and action.strip().isalnum()
        if chat_data is not None and (is_menu_action or is_valid_keyword):
            chat_data.pop(MARKET_SEARCH_PENDING_KEY, None)
        if not is_menu_action:
            await _reply_market_search_results(
                update=update,
                context=context,
                keyword=action,
            )
            return

    if bot_context.is_discovery_workflow and action in {
        MENU_DASHBOARD,
        MENU_TRADING,
        MENU_CONFIGURATION,
        MENU_EXCHANGE,
        MENU_MARKET,
        MENU_MARKET_OVERVIEW,
        MENU_INTERVAL,
        MENU_STREAM,
        MENU_START,
    }:
        await _show_navigation(
            update=update,
            title="Discovery Workflow",
            description=(
                "Single-symbol controls disembunyikan. Gunakan Status, Positions, "
                "runtime control, risk limits, atau Trading Mode."
            ),
            keyboard=_get_context_main_menu_keyboard(bot_context),
        )
        return

    if action == MENU_DASHBOARD:
        await _show_navigation(
            update=update,
            title="Dashboard",
            description="Pantau runtime, market, balance, dan posisi aktif.",
            keyboard=get_dashboard_menu_keyboard(),
        )
    elif action == MENU_TRADING:
        control = bot_context.runtime_control
        is_paused = control.is_paused if control is not None else True
        await _show_navigation(
            update=update,
            title="Trading Control",
            description="Kelola stream dan status trading dari satu tempat.",
            keyboard=get_trading_menu_keyboard(is_paused=is_paused),
        )
    elif action == MENU_CONFIGURATION:
        await _show_navigation(
            update=update,
            title="Configuration",
            description="Atur exchange, market, strategy, dan interval.",
            keyboard=get_configuration_menu_keyboard(),
        )
    elif action == MENU_ACTIVITY:
        await _show_navigation(
            update=update,
            title="Activity",
            description="Tinjau order, riwayat trade, dan diagnostic test.",
            keyboard=get_activity_menu_keyboard(),
        )
    elif action == MENU_HOME:
        await _show_navigation(
            update=update,
            title="Botragram Home",
            description="Pilih kategori sesuai pekerjaan yang ingin dilakukan.",
            keyboard=_get_context_main_menu_keyboard(bot_context),
        )
    elif action == MENU_STATUS:
        await status_command(update, context)
    elif action == MENU_POSITIONS:
        await positions_command(update, context)
    elif action == MENU_MARKET_OVERVIEW:
        await market_overview_command(update, context)
    elif action == MENU_MARKET:
        await market_command(update, context)
    elif action == MENU_ORDERS:
        await orders_command(update, context)
    elif action == MENU_BALANCE:
        await balance_command(update, context)
    elif action == MENU_HISTORY:
        await history_command(update, context)
    elif action == MENU_SETTINGS:
        await settings_command(update, context)
    elif action == MENU_EXCHANGE:
        await exchange_command(update, context)
    elif action == MENU_STRATEGY:
        await strategy_command(update, context)
    elif action == MENU_INTERVAL:
        await interval_command(update, context)
    elif action == MENU_STREAM:
        await stream_command(update, context)
    elif action in {MENU_START, MENU_RESUME}:
        await start_bot_command(update, context)
    elif action == MENU_PAUSE:
        await pause_bot_command(update, context)
    elif action == MENU_RISK_LIMITS:
        await risk_limits_command(update, context)
    elif action == MENU_TRADING_MODE:
        await trading_mode_command(update, context)
    elif action == MENU_TEST:
        await test_command(update, context)
    elif action == MENU_STOP:
        control = bot_context.runtime_control
        is_paused = control.is_paused if control is not None else True
        await update.message.reply_text(
            "ℹ️ <b>Gunakan Pause Bot untuk menghentikan trading dengan aman.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_trading_menu_keyboard(is_paused=is_paused),
        )
