"""Autonomous Telegram strategy-menu regressions."""

from __future__ import annotations

from botragram.constants.telegram import MENU_STRATEGY
from botragram.enums import ExecutionPolicy
from botragram.telegram.keyboards import get_main_menu_keyboard


def test_autonomous_live_home_exposes_strategy_control() -> None:
    """Keep Strategy directly reachable from the persistent LIVE menu."""
    for is_paused in (False, True):
        keyboard = get_main_menu_keyboard(
            execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
            is_paused=is_paused,
        )
        labels = {button.text for row in keyboard.keyboard for button in row}
        assert MENU_STRATEGY in labels


def test_autonomous_paper_home_exposes_strategy_control() -> None:
    """Keep Strategy directly reachable from autonomous PAPER as well."""
    keyboard = get_main_menu_keyboard(
        execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER,
        is_paused=True,
    )
    labels = {button.text for row in keyboard.keyboard for button in row}
    assert MENU_STRATEGY in labels
