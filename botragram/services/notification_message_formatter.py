"""
Botragram

Description:
    Transport-neutral formatting contract for application notifications.

Python:
    3.14+
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from botragram.models import ClosedPositionLifecycle, Order, Position, Trade

__all__ = ["NotificationMessageFormatter"]


class NotificationMessageFormatter(Protocol):
    """Format domain facts for the selected notification transport."""

    def drawdown_alert(
        self,
        *,
        current_drawdown_pct: Decimal,
        max_drawdown_pct: Decimal,
        current_equity: Decimal,
        high_water_equity: Decimal,
        asset: str,
        level: str,
    ) -> str:
        """Format a high-water-mark drawdown alert."""
        ...

    def paper_entry(
        self,
        *,
        order: Order,
        trade: Trade,
        position: Position,
        available_balance: Decimal,
    ) -> str:
        """Format a completed PAPER position entry."""
        ...

    def paper_exit(
        self,
        *,
        order: Order,
        trade: Trade,
        available_balance: Decimal,
        reason: str,
    ) -> str:
        """Format a completed PAPER position exit."""
        ...

    def partial_take_profit(
        self,
        *,
        position: Position,
        closed_quantity: Decimal,
        remaining_quantity: Decimal,
        exit_price: Decimal,
        new_stop_loss: Decimal | None,
        mode: str,
    ) -> str:
        """Format a partial take-profit event."""
        ...

    def trade_completed(
        self,
        *,
        lifecycle: ClosedPositionLifecycle,
        entry_fills: Sequence[Trade] | None,
        exit_fills: Sequence[Trade] | None,
    ) -> str:
        """Format a reconciled closed LIVE position."""
        ...

    def runtime_portfolio(
        self,
        *,
        available_balance: Decimal,
        positions: Sequence[Position],
        completed_cycles: int,
    ) -> str:
        """Format the periodic PAPER portfolio summary."""
        ...
