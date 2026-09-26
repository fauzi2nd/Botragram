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


def test_terminal_monitor_sorts_triggered_first_then_highest_bar() -> None:
    """Verify sorting: TRIGGERED first, then STALKING by current_bar desc."""
    now = datetime.now(UTC)
    s1 = StalkingSetup(
        symbol="SOLUSDT",
        side=PositionSide.SHORT,
        pattern_name="ENGULFING",
        anchor_price=Decimal("150"),
        invalidation_price=Decimal("155"),
        target_retest_price=Decimal("152"),
        htf_zone_label="HTF Extreme SHORT",
        current_bar=1,
        max_bars=7,
        started_at=now,
        updated_at=now,
        status=StalkingStatus.STALKING,
    )
    s2 = StalkingSetup(
        symbol="ETHUSDT",
        side=PositionSide.LONG,
        pattern_name="PINBAR",
        anchor_price=Decimal("3000"),
        invalidation_price=Decimal("2950"),
        target_retest_price=Decimal("2980"),
        htf_zone_label="HTF Extreme LONG",
        current_bar=5,
        max_bars=7,
        started_at=now,
        updated_at=now,
        status=StalkingStatus.STALKING,
    )
    s3 = StalkingSetup(
        symbol="AVNTUSDT",
        side=PositionSide.LONG,
        pattern_name="REVERSAL",
        anchor_price=Decimal("0.13155"),
        invalidation_price=Decimal("0.13014"),
        target_retest_price=Decimal("0.131055"),
        htf_zone_label="HTF Extreme LONG",
        current_bar=3,
        max_bars=7,
        started_at=now,
        updated_at=now,
        status=StalkingStatus.TRIGGERED,
    )
    s4 = StalkingSetup(
        symbol="DOGEUSDT",
        side=PositionSide.SHORT,
        pattern_name="ENGULFING",
        anchor_price=Decimal("0.20"),
        invalidation_price=Decimal("0.22"),
        target_retest_price=Decimal("0.21"),
        htf_zone_label="HTF Extreme SHORT",
        current_bar=7,
        max_bars=7,
        started_at=now,
        updated_at=now,
        status=StalkingStatus.EXPIRED,
    )

    # 1. Verify helper sorting order
    sorted_setups = TerminalMonitor.sort_stalking_setups((s1, s2, s3, s4))
    assert [s.symbol for s in sorted_setups] == [
        "AVNTUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "DOGEUSDT",
    ]

    # 2. Verify rendered table order
    monitor = _create_monitor(setups=(s1, s2, s3, s4))
    status = asyncio.run(monitor.collect_status())
    layout = monitor.render_dashboard(status)
    panel = layout["active_stalking"].renderable

    string_io = StringIO()
    console = Console(file=string_io, force_terminal=True, width=140)
    console.print(panel)
    output: str = string_io.getvalue()

    avnt_pos = output.find("AVNTUSDT")
    eth_pos = output.find("ETHUSDT")
    sol_pos = output.find("SOLUSDT")
    doge_pos = output.find("DOGEUSDT")

    assert avnt_pos != -1
    assert eth_pos != -1
    assert sol_pos != -1
    assert doge_pos != -1
    assert avnt_pos < eth_pos < sol_pos < doge_pos


def test_terminal_monitor_cleans_and_suspends_stalking_when_capacity_full() -> None:
    """When open positions reach capacity, stalking is paused and cleaned."""
    now = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    setup = StalkingSetup(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        pattern_name="PINBAR",
        anchor_price=Decimal("60000"),
        invalidation_price=Decimal("59000"),
        target_retest_price=Decimal("59500"),
        htf_zone_label="HTF Extreme LONG",
        current_bar=2,
        max_bars=7,
        started_at=now,
        updated_at=now,
        status=StalkingStatus.STALKING,
    )

    class StatefulStalkingProvider:
        def __init__(self) -> None:
            self.setups = [setup]
            self.paused = False

        def get_active_stalking_setups(self) -> tuple[StalkingSetup, ...]:
            return () if self.paused else tuple(self.setups)

        def clear_all(self) -> None:
            self.setups.clear()

        def set_paused(self, paused: bool) -> None:
            self.paused = paused
            if paused:
                self.setups.clear()

    provider = StatefulStalkingProvider()
    pos = Position(
        symbol="ETHUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("2000"),
        current_price=Decimal("2000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=now,
        updated_at=now,
    )

    class PositionsProvider:
        async def get_open_positions(self) -> Sequence[Position]:
            return (pos,)

    console = Console(file=StringIO(), force_terminal=True, width=140)
    monitor = ResponsiveTerminalMonitor(
        runtime_control=TradingRuntimeControl(symbol="BTCUSDT"),
        paper_balance_provider=FakePaperBalance(),
        live_balance_provider=FakeLiveBalance(),
        position_provider=PositionsProvider(),
        pnl_engine=PnLEngine(),
        trade_mode=TradeMode.PAPER,
        quote_asset="USDT",
        stalking_setup_provider=provider,
        max_open_positions=1,  # Capacity is 1, and 1 position is already open!
        console=console,
    )

    status = asyncio.run(monitor.collect_status())
    # 1. Stalking setups in status must be cleaned up / empty
    assert status.stalking_setups == ()
    assert provider.paused is True
    assert provider.setups == []

    # 2. Render stalking panel and verify clean suspended notice
    layout = monitor.render_dashboard(status)
    panel = layout["active_stalking"].renderable
    string_io = StringIO()
    c = Console(file=string_io, force_terminal=True, width=140)
    c.print(panel)
    output = string_io.getvalue()

    assert "POSITIONS FULL / STALKING SUSPENDED" in output
    assert "BTCUSDT" not in output
