"""
Botragram

Description:
    Stable Telegram import contracts after callback and presentation extraction.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.telegram import get_status_message as PackageStatusMessage
from botragram.telegram.callback_routes.callbacks import (
    handle_callback_query as RoutedCallbackQuery,
)
from botragram.telegram.callbacks import handle_callback_query
from botragram.telegram.keyboards import get_main_menu_keyboard
from botragram.telegram.messages import get_status_message
from botragram.telegram.presentation.keyboards import (
    get_main_menu_keyboard as PresentationMainMenuKeyboard,
)
from botragram.telegram.presentation.messages import (
    get_status_message as PresentationStatusMessage,
)

__all__: list[str] = []


def test_telegram_public_imports_preserve_callable_identity() -> None:
    """Legacy Telegram imports point at their extracted implementations."""
    assert handle_callback_query is RoutedCallbackQuery
    assert get_main_menu_keyboard is PresentationMainMenuKeyboard
    assert get_status_message is PresentationStatusMessage
    assert PackageStatusMessage is PresentationStatusMessage
