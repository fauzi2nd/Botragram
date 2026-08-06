"""Telegram chat authorization helpers."""

from __future__ import annotations

from collections.abc import Collection
from typing import Final, cast

from telegram import Update
from telegram.ext import ContextTypes

from botragram.telegram.context import ALLOWED_CHAT_IDS_KEY

__all__ = ["is_authorized_update", "is_chat_allowed"]


_EMPTY_IDS: Final[frozenset[int]] = frozenset()


def is_chat_allowed(*, chat_id: int | None, allowed_chat_ids: Collection[int]) -> bool:
    """Return whether a concrete chat is explicitly allow-listed."""
    return chat_id is not None and chat_id in allowed_chat_ids


def is_authorized_update(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Validate an update against chat IDs stored by the bot lifecycle."""
    chat = update.effective_chat
    raw_ids: object = context.bot_data.get(ALLOWED_CHAT_IDS_KEY, _EMPTY_IDS)
    allowed_ids = _get_allowed_ids(raw_ids)

    return is_chat_allowed(
        chat_id=chat.id if chat is not None else None,
        allowed_chat_ids=allowed_ids,
    )


def _get_allowed_ids(value: object) -> Collection[int]:
    """Return a validated immutable ID collection from bot data."""
    if not isinstance(value, (set, frozenset, list, tuple)):
        return _EMPTY_IDS

    items = cast(Collection[object], value)

    if all(isinstance(item, int) and not isinstance(item, bool) for item in items):
        return frozenset(
            item
            for item in items
            if isinstance(item, int) and not isinstance(item, bool)
        )

    return _EMPTY_IDS
