"""
Botragram

Description:
    Unit tests for Dedicated Active Setup Stalking terminal dashboard panel,
    ensuring correct layout positioning (directly above Managed Positions),
    status rendering, and candidate tracking presentation.

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
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from typing import Sequence

# =============================================================================
# Third-Party Imports
# =============================================================================
from rich.console import Console

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import TerminalMonitor, TradingRuntimeControl
from botragram.app.responsive_terminal_monitor import (
    TerminalMonitor as ResponsiveTerminalMonitor,
)
from botragram.engine import PnLEngine
from botragram.enums import (
    PositionSide,
    StalkingStatus,
    StrategyType,
    TradeMode,
)
from botragram.models import Position, StalkingSetup
from botragram.services.paper_trading_service import PaperPortfolioSnapshot

_START_TIME = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)


class FakePaperBalance:
    async def get_portfolio_snapshot(self) -> PaperPortfolioSnapshot:
        return PaperPortfolioSnapshot(
            available_balance=Decimal("10000"),
            realized_pnl=Decimal("0"),
        )


class FakeLiveBalance:
    async def get_free_balance(self, *, asset: str) -> Decimal:
        return Decimal("1000")


class FakePositions:
    async def get_open_positions(self) -> Sequence[Position]:
        return ()


class FakeStalkingProvider:
    def __init__(self, setups: tuple[StalkingSetup, ...] = ()) -> None:
        self.setups = setups

    def get_active_stalking_setups(self) -> tuple[StalkingSetup, ...]:
        return self.setups


def _create_monitor(
    *,
    setups: tuple[StalkingSetup, ...] = (),
    width: int = 140,
) -> TerminalMonitor:
    console = Console(file=StringIO(), force_terminal=True, width=width)
    return TerminalMonitor(
        runtime_control=TradingRuntimeControl(
            strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI
        ),
        paper_balance_provider=FakePaperBalance(),
        live_balance_provider=FakeLiveBalance(),
        position_provider=FakePositions(),
        pnl_engine=PnLEngine(),
        trade_mode=TradeMode.PAPER,
        quote_asset="USDT",
        stalking_setup_provider=FakeStalkingProvider(setups=setups),
        console=console,
    )


def _create_responsive_monitor(
    *,
    setups: tuple[StalkingSetup, ...] = (),
    width: int = 120,
) -> ResponsiveTerminalMonitor:
    console = Console(file=StringIO(), force_terminal=True, width=width)
    return ResponsiveTerminalMonitor(
        runtime_control=TradingRuntimeControl(
            strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI
        ),
        paper_balance_provider=FakePaperBalance(),
        live_balance_provider=FakeLiveBalance(),
        position_provider=FakePositions(),
        pnl_engine=PnLEngine(),
        trade_mode=TradeMode.PAPER,
        quote_asset="USDT",
        stalking_setup_provider=FakeStalkingProvider(setups=setups),
        console=console,
    )


def test_terminal_monitor_stalking_panel_layout_position() -> None:
    """Verify active_stalking is placed directly above managed_positions."""
    monitor = _create_monitor()
    status = asyncio.run(monitor.collect_status())
    layout = monitor.render_dashboard(status)

    # Check root children order
    children = [child.name for child in layout.children]
    assert "summary" in children
    assert "active_stalking" in children
    assert "managed_positions" in children
    assert "logs" in children

    # active_stalking must immediately precede managed_positions
    stalking_idx = children.index("active_stalking")
    positions_idx = children.index("managed_positions")
    assert stalking_idx == positions_idx - 1


def test_stalking_panel_renders_empty_state() -> None:
    """When no candidates are stalked, panel renders idle waiting row."""
    monitor = _create_monitor(setups=())
    status = asyncio.run(monitor.collect_status())
    layout = monitor.render_dashboard(status)
    panel = layout["active_stalking"].renderable

    console = Console(file=StringIO(), force_terminal=True, width=120)
    console.print(panel)
    output = console.file.getvalue()  # type: ignore[attr-defined]

    assert "Active Setup Stalking" in output
    assert "IDLE / WAITING CANDIDATES" in output


def test_stalking_panel_renders_active_candidate_details() -> None:
    """When setups exist, panel renders all candidate metrics."""
    now = datetime.now(UTC)
    setup = StalkingSetup(
        symbol="BTCUSDT",
        side=PositionSide.SHORT,
        pattern_name="ENGULFING",
        anchor_price=Decimal("95000.50"),
        invalidation_price=Decimal("95800.00"),
        target_retest_price=Decimal("95400.00"),
        htf_zone_label="15m Upper Band",
        current_bar=2,
        max_bars=7,
        started_at=now,
        updated_at=now,
        status=StalkingStatus.STALKING,
    )

    monitor = _create_monitor(setups=(setup,))
    status = asyncio.run(monitor.collect_status())
    assert len(status.stalking_setups) == 1

    layout = monitor.render_dashboard(status)
    panel = layout["active_stalking"].renderable
    console = Console(file=StringIO(), force_terminal=True, width=140)
    console.print(panel)
    output = console.file.getvalue()  # type: ignore[attr-defined]

    assert "BTCUSDT" in output
    assert "SHORT" in output
    assert "ENGULFING" in output
    assert "95000.5" in output
    assert "95400" in output
    assert "95800" in output
    assert "Bar 2/7" in output
    assert "STALKING" in output
    assert "15m Upper Band" in output


def test_responsive_terminal_monitor_includes_stalking_panel() -> None:
    """Verify responsive terminal monitor includes active_stalking."""
    # Medium layout (width 120)
    monitor_medium = _create_responsive_monitor(width=120)
    status_med = asyncio.run(monitor_medium.collect_status())
    layout_med = monitor_medium.render_dashboard(status_med)
    children_med = [child.name for child in layout_med.children]
    assert "active_stalking" in children_med
    assert (
        children_med.index("active_stalking")
        == children_med.index("managed_positions") - 1
    )

    # Compact layout (width 80)
    monitor_compact = _create_responsive_monitor(width=80)
    status_comp = asyncio.run(monitor_compact.collect_status())
    layout_comp = monitor_compact.render_dashboard(status_comp)
    children_comp = [child.name for child in layout_comp.children]
    assert "active_stalking" in children_comp
    assert (
        children_comp.index("active_stalking")
        == children_comp.index("managed_positions") - 1
    )
