"""Guarded Telegram strategy selection for every execution workflow."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from botragram.constants.telegram import DEFAULT_PARSE_MODE
from botragram.enums import StrategyType
from botragram.exceptions import ExecutionPolicySwitchBlockedError
from botragram.telegram.access import is_authorized_update
from botragram.telegram.context import BOT_CONTEXT_KEY, BotContext
from botragram.telegram.keyboards import get_strategy_keyboard
from botragram.telegram.messages import get_strategy_message

__all__ = ["strategy_switch_callback", "strategy_switch_command"]

_STRATEGY_CALLBACK_PREFIX = "cb_strategy_"
_FAST_PERIOD = 9
_SLOW_PERIOD = 21


@runtime_checkable
class _StrategySessionSwitcher(Protocol):
    """Replace the immutable strategy owned by one runtime session."""

    @property
    def current_strategy_type(self) -> StrategyType:
        """Return the strategy owned by the current session."""
        ...

    async def prepare_strategy(self, *, strategy_type: StrategyType) -> bool:
        """Validate and stage one safe strategy session replacement."""
        ...

    def commit_strategy(self, *, strategy_type: StrategyType) -> None:
        """Commit an already-staged strategy replacement."""
        ...


def _get_context(context: ContextTypes.DEFAULT_TYPE) -> BotContext:
    """Return the application context or safe defaults."""
    value = context.bot_data.get(BOT_CONTEXT_KEY)
    return value if isinstance(value, BotContext) else BotContext()


def _get_switcher(bot_context: BotContext) -> _StrategySessionSwitcher | None:
    """Return the strategy-aware session switcher when available."""
    switcher = bot_context.market_type_switcher
    return switcher if isinstance(switcher, _StrategySessionSwitcher) else None


def _current_strategy(bot_context: BotContext) -> StrategyType:
    """Return the authoritative current session strategy."""
    switcher = _get_switcher(bot_context)
    if switcher is not None:
        return switcher.current_strategy_type
    control = bot_context.runtime_control
    if control is not None:
        return control.strategy_type
    try:
        return StrategyType(bot_context.strategy_name)
    except ValueError:
        return StrategyType.EMA_CROSS


def _flatten_for_strategy_keyboard(
    *,
    current: StrategyType,
    target: StrategyType,
) -> InlineKeyboardMarkup:
    """Offer an explicit flatten action bound to the requested strategy."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⚠️ Close All & Apply Strategy",
                    callback_data=f"cb_strategy_flatten_{target.value}",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Back to Strategy",
                    callback_data=f"cb_strategy_{current.value}",
                )
            ],
        ]
    )


async def strategy_switch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Show the strategy selector in both single-symbol and discovery workflows."""
    if update.message is None:
        return
    if not is_authorized_update(update=update, context=context):
        return

    bot_context = _get_context(context)
    strategy = _current_strategy(bot_context)
    await update.message.reply_text(
        get_strategy_message(
            strategy.value,
            _FAST_PERIOD,
            _SLOW_PERIOD,
            confirmed=True,
        ),
        parse_mode=DEFAULT_PARSE_MODE,
        reply_markup=get_strategy_keyboard(strategy.value, confirmed=True),
    )


async def strategy_switch_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Safely rebuild the runtime session with the selected strategy."""
    query = update.callback_query
    if query is None or not is_authorized_update(update=update, context=context):
        return
    await query.answer()

    raw_strategy = (query.data or "").removeprefix(_STRATEGY_CALLBACK_PREFIX)
    try:
        target = StrategyType(raw_strategy)
    except ValueError:
        await query.edit_message_text(
            "⚠️ <b>Strategy tidak didukung.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    bot_context = _get_context(context)
    switcher = _get_switcher(bot_context)
    if switcher is None:
        await query.edit_message_text(
            "⚠️ <b>Strategy switch tidak tersedia pada runtime ini.</b>",
            parse_mode=DEFAULT_PARSE_MODE,
        )
        return

    current = switcher.current_strategy_type
    try:
        changed = await switcher.prepare_strategy(strategy_type=target)
    except ExecutionPolicySwitchBlockedError as error:
        if error.active_position_count > 0:
            await query.edit_message_text(
                "⚠️ <b>Portfolio harus flat sebelum mengganti strategy.</b>\n\n"
                f"Posisi aktif: <b>{error.active_position_count}</b>\n"
                f"Target strategy: <code>{target.value}</code>\n\n"
                "Gunakan tombol di bawah untuk menutup portfolio secara eksplisit. "
                "Target strategy akan dibawa sampai portfolio terbukti flat dan "
                "kemudian diterapkan melalui soft restart.",
                parse_mode=DEFAULT_PARSE_MODE,
                reply_markup=_flatten_for_strategy_keyboard(
                    current=current,
                    target=target,
                ),
            )
            return
        await query.edit_message_text(
            f"⚠️ <b>{error}</b>\n\n"
            "Jeda runtime dan pastikan recovery/protection siap sebelum mengganti "
            "strategy.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_strategy_keyboard(current.value, confirmed=True),
        )
        return
    except (RuntimeError, ValueError) as error:
        await query.edit_message_text(
            f"⚠️ <b>{error}</b>",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_strategy_keyboard(current.value, confirmed=True),
        )
        return

    if not changed:
        await query.edit_message_text(
            get_strategy_message(
                current.value,
                _FAST_PERIOD,
                _SLOW_PERIOD,
                confirmed=True,
            )
            + "\n\nStrategy tersebut sudah aktif.",
            parse_mode=DEFAULT_PARSE_MODE,
            reply_markup=get_strategy_keyboard(current.value, confirmed=True),
        )
        return

    await query.edit_message_text(
        "🔄 <b>Strategy sedang diganti.</b>\n\n"
        f"<code>{current.value}</code> → <code>{target.value}</code>\n\n"
        "Trading session akan direbuild dalam process yang sama. "
        "Session baru tetap PAUSED sampai operator melanjutkan trading.",
        parse_mode=DEFAULT_PARSE_MODE,
    )
    switcher.commit_strategy(strategy_type=target)
