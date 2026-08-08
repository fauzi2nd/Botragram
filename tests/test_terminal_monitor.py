"""
Botragram

Description:
    Terminal portfolio and stream telemetry monitor tests.

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
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest
from rich.console import Console

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import TerminalMonitor, TradingRuntimeControl
from botragram.engine import PnLEngine
from botragram.enums import PositionSide, TradeMode
from botragram.models import Position
from botragram.services import PaperPortfolioSnapshot


# =============================================================================
# Test Fakes
# =============================================================================
@dataclass(slots=True, kw_only=True)
class FakePaperBalanceProvider:
    """Return a deterministic paper balance and count reads."""

    balance: Decimal
    realized_pnl: Decimal = Decimal("0")
    calls: int = 0

    async def get_portfolio_snapshot(self) -> PaperPortfolioSnapshot:
        """Return the configured paper portfolio metrics."""
        self.calls += 1
        return PaperPortfolioSnapshot(
            available_balance=self.balance,
            realized_pnl=self.realized_pnl,
        )


@dataclass(slots=True, kw_only=True)
class FakeLiveBalanceProvider:
    """Return a deterministic exchange balance and count reads."""

    balance: Decimal
    calls: int = 0

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return the configured exchange balance."""
        assert asset == "USDT"
        self.calls += 1
        return self.balance


@dataclass(slots=True, kw_only=True, frozen=True)
class FakePositionProvider:
    """Return deterministic active positions."""

    positions: tuple[Position, ...] = ()

    async def get_open_positions(self) -> Sequence[Position]:
        """Return configured positions."""
        return self.positions


class RecordingAlternateScreenConsole(Console):
    """Record alternate-screen transitions independently of terminal support."""

    def __init__(self) -> None:
        """Initialize a deterministic Windows-compatible test console."""
        super().__init__(
            file=StringIO(),
            force_terminal=True,
            width=140,
        )
        self.alt_screen_states: list[bool] = []

    def set_alt_screen(self, enable: bool = True) -> bool:
        """Record and delegate one alternate-screen transition."""
        self.alt_screen_states.append(enable)
        return super().set_alt_screen(enable)


# =============================================================================
# Test Helpers
# =============================================================================
def _create_position() -> Position:
    """Create one long position for stream-mark PnL testing."""
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("2"),
        entry_price=Decimal("100"),
        current_price=Decimal("101"),
        unrealized_pnl=Decimal("2"),
        leverage=1,
        opened_at=observed_at,
        updated_at=observed_at,
        stop_loss=Decimal("98"),
        take_profit=Decimal("104"),
    )


def _create_monitor(
    *,
    runtime_control: TradingRuntimeControl | None = None,
    paper_balance: FakePaperBalanceProvider | None = None,
    live_balance: FakeLiveBalanceProvider | None = None,
    positions: tuple[Position, ...] = (),
    trade_mode: TradeMode = TradeMode.PAPER,
    output: list[str] | None = None,
    console: Console | None = None,
    refresh_interval_seconds: float = 1.0,
) -> TerminalMonitor:
    """Create a terminal monitor with deterministic dependencies."""
    lines = output if output is not None else []
    terminal_console = console

    if terminal_console is None:
        terminal_console = Console(
            file=StringIO(),
            force_terminal=True,
            width=140,
        )

    return TerminalMonitor(
        runtime_control=(
            runtime_control if runtime_control is not None else TradingRuntimeControl()
        ),
        paper_balance_provider=(
            paper_balance
            if paper_balance is not None
            else FakePaperBalanceProvider(balance=Decimal("10000"))
        ),
        live_balance_provider=(
            live_balance
            if live_balance is not None
            else FakeLiveBalanceProvider(balance=Decimal("500"))
        ),
        position_provider=FakePositionProvider(positions=positions),
        pnl_engine=PnLEngine(),
        trade_mode=trade_mode,
        quote_asset="usdt",
        console=terminal_console,
        output=lines.append,
        refresh_interval_seconds=refresh_interval_seconds,
    )


# =============================================================================
# Snapshot and Rendering Tests
# =============================================================================
def test_terminal_monitor_renders_stream_marked_portfolio_status() -> None:
    """Render balance, position PnL, and millisecond stream telemetry."""
    asyncio.run(_run_terminal_snapshot_test())


async def _run_terminal_snapshot_test() -> None:
    """Collect one stream-backed terminal snapshot."""
    control = TradingRuntimeControl(symbol="BTCUSDT")
    control.set_stream_enabled(True)
    control.record_stream_tick(price=Decimal("110"))
    lines: list[str] = []
    monitor = _create_monitor(
        runtime_control=control,
        paper_balance=FakePaperBalanceProvider(
            balance=Decimal("10000"),
            realized_pnl=Decimal("46.925025"),
        ),
        positions=(_create_position(),),
        output=lines,
    )

    status = await monitor.collect_status()
    line = await monitor.refresh()

    assert status.balance == Decimal("10000")
    assert status.position_count == 1
    assert status.unrealized_pnl == Decimal("20")
    assert status.realized_pnl == Decimal("46.925025")
    assert status.stream.enabled
    assert status.stream.event_count == 1
    assert status.stream_age_ms is not None
    assert status.stream_age_ms >= 0
    assert "balance=10,000.00 USDT" in line
    assert "positions=1" in line
    assert "pnl=+20.00 USDT" in line
    assert "realized=+46.93 USDT" in line
    assert "stream=ON price=110" in line
    assert "age=" in line
    assert lines == [line]

    control.set_stream_enabled(False)
    stopped_status = await monitor.collect_status()
    assert stopped_status.unrealized_pnl == Decimal("2")


def test_terminal_monitor_renders_three_rich_dashboard_panels() -> None:
    """Render status, stream, and buffered logs in the requested layout."""
    asyncio.run(_run_rich_dashboard_render_test())


async def _run_rich_dashboard_render_test() -> None:
    """Capture a deterministic Rich dashboard frame."""
    control = TradingRuntimeControl(symbol="BTCUSDT")
    control.set_stream_enabled(True)
    control.record_stream_tick(price=Decimal("110"))
    monitor = _create_monitor(
        runtime_control=control,
        positions=(_create_position(),),
    )
    record = logging.LogRecord(
        name="botragram.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Dashboard log event",
        args=(),
        exc_info=None,
    )
    monitor.log_handler.emit(record)
    status = await monitor.collect_status()
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=140)

    console.print(monitor.render_dashboard(status))
    rendered = output.getvalue()

    assert "Status & Portfolio" in rendered
    assert "Market Stream" in rendered
    assert "Log Messages" in rendered
    assert "CONFIGURING" in rendered
    assert "Dashboard log event" in rendered
    assert "LONG | Qty 2 | 1x" in rendered
    assert "100.00000000 / 110.00000000" in rendered
    assert "Risk @ SL" in rendered
    assert "4.00 USDT" in rendered
    assert "98.00000000 / 104.00000000" in rendered
    assert "Realized PnL" in rendered
    assert "+0.00 USDT" in rendered


def test_terminal_monitor_caches_live_balance_reads() -> None:
    """Avoid polling the authenticated account on every terminal refresh."""
    asyncio.run(_run_live_balance_cache_test())


async def _run_live_balance_cache_test() -> None:
    """Collect two LIVE snapshots inside one balance cache window."""
    paper_balance = FakePaperBalanceProvider(balance=Decimal("10000"))
    live_balance = FakeLiveBalanceProvider(balance=Decimal("321.50"))
    monitor = _create_monitor(
        paper_balance=paper_balance,
        live_balance=live_balance,
        trade_mode=TradeMode.LIVE,
    )

    first = await monitor.collect_status()
    second = await monitor.collect_status()

    assert first.balance == Decimal("321.50")
    assert second.balance == Decimal("321.50")
    assert live_balance.calls == 1
    assert paper_balance.calls == 0
    assert first.realized_pnl is None
    assert second.realized_pnl is None


# =============================================================================
# Lifecycle and Validation Tests
# =============================================================================
def test_terminal_monitor_stops_without_waiting_for_refresh_interval() -> None:
    """Stop terminal telemetry immediately and deterministically."""
    asyncio.run(_run_terminal_monitor_stop_test())


async def _run_terminal_monitor_stop_test() -> None:
    """Start the monitor, observe output, and request graceful shutdown."""
    lines: list[str] = []
    console = RecordingAlternateScreenConsole()
    monitor = _create_monitor(
        output=lines,
        console=console,
        refresh_interval_seconds=60.0,
    )
    task = asyncio.create_task(monitor.run())

    for _ in range(10):
        if lines:
            break
        await asyncio.sleep(0)

    monitor.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert len(lines) == 1
    assert console.alt_screen_states
    assert console.alt_screen_states[0]


@pytest.mark.parametrize(
    ("refresh_interval", "live_balance_interval", "message"),
    (
        (0.0, 10.0, "refresh interval"),
        (1.0, 0.0, "balance refresh interval"),
    ),
)
def test_terminal_monitor_rejects_invalid_intervals(
    refresh_interval: float,
    live_balance_interval: float,
    message: str,
) -> None:
    """Reject non-positive terminal and exchange refresh intervals."""
    with pytest.raises(ValueError, match=message):
        TerminalMonitor(
            runtime_control=TradingRuntimeControl(),
            paper_balance_provider=FakePaperBalanceProvider(balance=Decimal("10000")),
            live_balance_provider=FakeLiveBalanceProvider(balance=Decimal("500")),
            position_provider=FakePositionProvider(),
            pnl_engine=PnLEngine(),
            trade_mode=TradeMode.PAPER,
            quote_asset="USDT",
            output=lambda line: None,
            refresh_interval_seconds=refresh_interval,
            live_balance_refresh_seconds=live_balance_interval,
        )
