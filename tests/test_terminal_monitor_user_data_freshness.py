"""Terminal presentation regression for private-stream freshness."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from botragram.app.terminal_monitor import TerminalMonitor
from botragram.enums import Interval, LiveFuturesUserDataStatus, PositionSide
from botragram.models import FuturesUserDataPositionUpdate, Position
from botragram.services.live_futures_user_data_cache import LiveFuturesUserDataSnapshot

_NOW = datetime(2026, 8, 25, tzinfo=UTC)


def test_terminal_does_not_overlay_resyncing_position_cache() -> None:
    """Retain durable managed data while a private-stream cache is stale."""
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("101"),
        unrealized_pnl=Decimal("1"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        interval=Interval.M1,
    )
    user_data = LiveFuturesUserDataSnapshot(
        status=LiveFuturesUserDataStatus.RESYNCING,
        last_event_at=_NOW,
        last_snapshot_at=_NOW,
        balances=(),
        positions=(),
        position_updates=(
            FuturesUserDataPositionUpdate(
                symbol="BTCUSDT",
                quantity=Decimal("2"),
                entry_price=Decimal("100"),
                unrealized_pnl=Decimal("2"),
            ),
        ),
        recent_orders=(),
    )

    merged = TerminalMonitor.merge_live_futures_position_updates(
        positions=(position,),
        user_data=user_data,
    )

    assert merged == (position,)


def test_terminal_formats_signed_position_pnl() -> None:
    """Make profit and loss unambiguous in the managed-position table."""
    assert TerminalMonitor.format_position_pnl(Decimal("1.2345678")) == "+1.2345678"
    assert TerminalMonitor.format_position_pnl(Decimal("-1.2345678")) == "-1.2345678"
    assert TerminalMonitor.format_position_pnl(Decimal("0")) == "0"


def test_terminal_formats_signed_position_roi() -> None:
    """Calculate and format accurate ROI percentage with sign."""
    # Profit: Notional = 100 * 1 = 100, Margin = 100 / 10 = 10, PnL = 1 -> +10.00%
    assert (
        TerminalMonitor.format_position_roi(
            unrealized_pnl=Decimal("1"),
            entry_price=Decimal("100"),
            quantity=Decimal("1"),
            leverage=10,
        )
        == "+10.00%"
    )
    # Loss: Notional = 50 * 2 = 100, Margin = 100 / 20 = 5, PnL = -0.25 -> -5.00%
    assert (
        TerminalMonitor.format_position_roi(
            unrealized_pnl=Decimal("-0.25"),
            entry_price=Decimal("50"),
            quantity=Decimal("2"),
            leverage=20,
        )
        == "-5.00%"
    )
    # Zero or invalid
    assert (
        TerminalMonitor.format_position_roi(
            unrealized_pnl=Decimal("0"),
            entry_price=Decimal("100"),
            quantity=Decimal("1"),
            leverage=1,
        )
        == "0.00%"
    )
    assert (
        TerminalMonitor.format_position_roi(
            unrealized_pnl=Decimal("1"),
            entry_price=Decimal("0"),
            quantity=Decimal("0"),
            leverage=1,
        )
        == "0.00%"
    )
