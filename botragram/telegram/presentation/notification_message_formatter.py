"""
Botragram

Description:
    Telegram HTML adapter for application notification facts.

Python:
    3.14+
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from botragram.models import ClosedPositionLifecycle, Order, Position, Trade
from botragram.telegram.presentation.messages import (
    get_drawdown_alert_message,
    get_paper_entry_message,
    get_paper_exit_message,
    get_partial_tp_message,
    get_runtime_portfolio_message,
    get_trade_completed_message,
)

__all__ = ["TelegramNotificationMessageFormatter"]


@dataclass(slots=True, frozen=True)
class TelegramNotificationMessageFormatter:
    """Render application notifications with existing Telegram HTML templates."""

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
        """Render a high-water-mark drawdown alert."""
        return get_drawdown_alert_message(
            current_drawdown_pct=current_drawdown_pct,
            max_drawdown_pct=max_drawdown_pct,
            current_equity=current_equity,
            high_water_equity=high_water_equity,
            asset=asset,
            level=level,
        )

    def paper_entry(
        self,
        *,
        order: Order,
        trade: Trade,
        position: Position,
        available_balance: Decimal,
    ) -> str:
        """Render one PAPER position entry."""
        return get_paper_entry_message(
            order=order,
            trade=trade,
            position=position,
            available_balance=available_balance,
        )

    def paper_exit(
        self,
        *,
        order: Order,
        trade: Trade,
        available_balance: Decimal,
        reason: str,
    ) -> str:
        """Render one PAPER position exit."""
        return get_paper_exit_message(
            order=order,
            trade=trade,
            available_balance=available_balance,
            reason=reason,
        )

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
        """Render one partial take-profit event."""
        return get_partial_tp_message(
            position=position,
            closed_quantity=closed_quantity,
            remaining_quantity=remaining_quantity,
            exit_price=exit_price,
            new_stop_loss=new_stop_loss,
            mode=mode,
        )

    def trade_completed(
        self,
        *,
        lifecycle: ClosedPositionLifecycle,
        entry_fills: Sequence[Trade] | None,
        exit_fills: Sequence[Trade] | None,
    ) -> str:
        """Render a reconciled closed LIVE position."""
        return get_trade_completed_message(
            lifecycle=lifecycle,
            entry_fills=entry_fills,
            exit_fills=exit_fills,
        )

    def runtime_portfolio(
        self,
        *,
        available_balance: Decimal,
        positions: Sequence[Position],
        completed_cycles: int,
    ) -> str:
        """Render a periodic PAPER portfolio summary."""
        return get_runtime_portfolio_message(
            available_balance=available_balance,
            positions=positions,
            completed_cycles=completed_cycles,
        )
