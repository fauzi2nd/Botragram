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
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from time import monotonic

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest
from rich.console import Console

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import TerminalMonitor, TradingRuntimeControl
from botragram.app.global_discovery_telemetry import GlobalDiscoveryTelemetry
from botragram.engine import PnLEngine
from botragram.enums import (
    AutonomousLiveRecoveryReason,
    AutonomousLiveRecoveryStatus,
    GlobalDiscoveryCycleOutcome,
    Interval,
    LiveFuturesUserDataStatus,
    LiveMarketStreamLifecycleStatus,
    LiveRuntimeHealthReason,
    LiveRuntimeHealthStatus,
    PositionSide,
    SignalType,
    StrategyType,
    SubmissionAttemptStatus,
    TradeMode,
)
from botragram.models import (
    AutonomousLiveRecoverySnapshot,
    DiscoveryUniverseBatch,
    FuturesUserDataPositionUpdate,
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveProtectionMonitorState,
    LiveRuntimeHealthSnapshot,
    LiveRuntimePositionContext,
    MarketUniverseEntry,
    Position,
    RuntimeRiskLimits,
    Signal,
    TradingDecision,
    TradingResult,
)
from botragram.services import PaperPortfolioSnapshot
from botragram.services.live_futures_user_data_cache import (
    LiveFuturesUserDataSnapshot,
)
from botragram.services.live_trading_performance_service import (
    TradingPerformanceSnapshot,
)


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


@dataclass(slots=True, kw_only=True)
class TransitioningPositionProvider:
    """Change runtime contexts while an async terminal snapshot is in flight."""

    runtime_control: TradingRuntimeControl
    positions: tuple[Position, ...]
    contexts: tuple[LiveRuntimePositionContext, ...]

    async def get_open_positions(self) -> Sequence[Position]:
        """Advance runtime ownership before returning the position snapshot."""
        self.runtime_control.set_runtime_contexts(contexts=self.contexts)
        return self.positions


@dataclass(slots=True, kw_only=True, frozen=True)
class FakeLiveFuturesUserDataProvider:
    """Return one deterministic private Futures cache snapshot."""

    snapshot: LiveFuturesUserDataSnapshot

    async def get_snapshot(self) -> LiveFuturesUserDataSnapshot:
        """Return the configured cache snapshot without exchange I/O."""
        return self.snapshot


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


@dataclass(slots=True, kw_only=True, frozen=True)
class FakeLiveRuntimeHealthProvider:
    """Return one immutable LIVE health snapshot for terminal rendering."""

    snapshot: LiveRuntimeHealthSnapshot

    def get_snapshot(self) -> LiveRuntimeHealthSnapshot:
        """Return the configured read-only health snapshot."""
        return self.snapshot


@dataclass(slots=True, kw_only=True)
class CountingLiveRuntimeHealthProvider:
    """Return LIVE health while recording whether presentation requested it."""

    snapshot: LiveRuntimeHealthSnapshot
    calls: int = 0

    def get_snapshot(self) -> LiveRuntimeHealthSnapshot:
        """Return the configured snapshot and record one read."""
        self.calls += 1
        return self.snapshot


@dataclass(slots=True, kw_only=True)
class FakeRuntimeRiskLimitProvider:
    """Expose a replaceable current runtime-limit snapshot."""

    snapshot: RuntimeRiskLimits

    def get_snapshot(self) -> RuntimeRiskLimits:
        """Return the current immutable runtime limits."""
        return self.snapshot


@dataclass(slots=True, kw_only=True, frozen=True)
class FakeRecoveryProvider:
    """Return a deterministic read-only autonomous recovery snapshot."""

    snapshot: AutonomousLiveRecoverySnapshot

    async def get_snapshot(self) -> AutonomousLiveRecoverySnapshot:
        """Return the configured immutable recovery snapshot."""
        return self.snapshot


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
    configured_strategy_type: StrategyType = StrategyType.EMA_CROSS,
    runtime_risk_limits: FakeRuntimeRiskLimitProvider | None = None,
    output: list[str] | None = None,
    console: Console | None = None,
    refresh_interval_seconds: float = 1.0,
    live_runtime_health: LiveRuntimeHealthSnapshot | None = None,
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
        configured_strategy_type=configured_strategy_type,
        runtime_risk_limit_provider=runtime_risk_limits,
        live_runtime_health_service=(
            FakeLiveRuntimeHealthProvider(snapshot=live_runtime_health)
            if live_runtime_health is not None
            else None
        ),
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


def test_terminal_zero_position_global_discovery_is_truthful() -> None:
    """Show autonomous TESTNET discovery without a false BTC stream context."""
    asyncio.run(_run_zero_position_global_discovery_test())


def test_terminal_renders_completed_global_candidate() -> None:
    """Render completed candidate telemetry from an existing trading result."""
    asyncio.run(_run_completed_candidate_test())


def test_terminal_renders_capacity_skipped_global_discovery() -> None:
    """Keep the runner waiting while the last discovery outcome shows capacity."""
    asyncio.run(_run_capacity_skipped_global_discovery_test())


async def _run_completed_candidate_test() -> None:
    """Render exact ranked-window and candidate telemetry after completion."""
    signal = Signal(
        symbol="ETHUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.9"),
        strategy_name="test_strategy",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    result = TradingResult(
        executed=False,
        decision=TradingDecision(
            should_execute=False,
            signal=signal,
            risk_result=None,
            reason="risk_rejected",
        ),
        order=None,
        reason="risk_rejected",
    )
    batch = DiscoveryUniverseBatch(
        entries=(
            MarketUniverseEntry(
                symbol="ETHUSDT",
                quote_volume=Decimal("1000"),
            ),
        ),
        universe_size=100,
        rank_start=21,
        rank_end=21,
    )
    telemetry = GlobalDiscoveryTelemetry(
        interval=Interval.M1,
        max_symbols=20,
        universe_limit=100,
        batch_size=20,
        top_n=5,
    )
    telemetry.begin_cycle(interval=Interval.M1)
    telemetry.complete_cycle(
        results=(result,),
        batch=batch,
        signals=(signal,),
    )
    telemetry.wait_until(next_eligible_monotonic=monotonic() + 60)
    monitor = _create_monitor(trade_mode=TradeMode.LIVE)
    monitor.global_discovery_telemetry_provider = telemetry
    status = await monitor.collect_status()
    output = StringIO()
    Console(file=output, force_terminal=False, width=180, height=60).print(
        monitor.render_dashboard(status)
    )
    rendered = output.getvalue()

    assert status.global_discovery is not None
    assert status.global_discovery.last_outcome is GlobalDiscoveryCycleOutcome.COMPLETED
    assert status.global_discovery.scanned_count == 1
    assert status.global_discovery.rank_start == 21
    assert status.global_discovery.rank_end == 21
    assert "WAITING #1" in rendered
    assert "U100/B20/T5" in rendered
    assert "21-21 / 100" in rendered
    assert "Scanned" in rendered
    assert "ETHUSDT" in rendered
    assert "BUY" in rendered
    assert "90%" in rendered
    assert "RISK REJECT" in rendered
    assert "Confidence" not in rendered
    assert "Score" in rendered


async def _run_capacity_skipped_global_discovery_test() -> None:
    """Render a capacity skip separately from the current runner phase."""
    telemetry = GlobalDiscoveryTelemetry(
        interval=Interval.M1,
        max_symbols=20,
        universe_limit=100,
        batch_size=20,
        top_n=5,
    )
    telemetry.begin_cycle(interval=Interval.M1)
    telemetry.complete_cycle(results=(), skipped_capacity=True)
    telemetry.wait_until(next_eligible_monotonic=monotonic() + 10)
    monitor = _create_monitor(trade_mode=TradeMode.LIVE)
    monitor.global_discovery_telemetry_provider = telemetry
    status = await monitor.collect_status()
    output = StringIO()
    Console(file=output, force_terminal=False, width=180, height=60).print(
        monitor.render_dashboard(status)
    )
    rendered = output.getvalue()

    assert status.global_discovery is not None
    assert (
        status.global_discovery.last_outcome
        is GlobalDiscoveryCycleOutcome.SKIPPED_CAPACITY
    )
    assert status.global_discovery.scanned_count == 0
    assert "WAITING #1" in rendered
    assert "Last Result" in rendered
    assert "CAPACITY" in rendered
    assert "U100/B20/T5" in rendered
    assert "Scanned" in rendered


async def _run_zero_position_global_discovery_test() -> None:
    """Render a zero-position autonomous LIVE snapshot using local telemetry."""
    health = LiveRuntimeHealthSnapshot(
        status=LiveRuntimeHealthStatus.ACTIVE,
        reason=None,
        contexts=(),
        affected_contexts=(),
        authorization_present=True,
        authorization_exact=True,
        runner_paused=False,
        cycle_in_progress=False,
        stream_states=(),
        monitor_states=(),
    )
    telemetry = GlobalDiscoveryTelemetry(
        interval=Interval.M1,
        max_symbols=20,
        top_n=5,
    )
    telemetry.begin_cycle(interval=Interval.M1)
    telemetry.wait_until(next_eligible_monotonic=monotonic() + 60)
    runtime_limits = FakeRuntimeRiskLimitProvider(
        snapshot=RuntimeRiskLimits(
            max_open_positions=1,
            max_position_size_usdt=Decimal("5"),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_by="test",
        )
    )
    monitor = _create_monitor(
        trade_mode=TradeMode.LIVE,
        configured_strategy_type=StrategyType.SUPERTREND,
        runtime_risk_limits=runtime_limits,
        live_runtime_health=health,
        live_balance=FakeLiveBalanceProvider(balance=Decimal("321.50")),
    )
    monitor.global_discovery_telemetry_provider = telemetry
    monitor.runtime_control.resume_global_cycle()
    monitor.autonomous_live_recovery_observability_service = FakeRecoveryProvider(
        snapshot=AutonomousLiveRecoverySnapshot(
            status=AutonomousLiveRecoveryStatus.CLEAR,
            reason=None,
            incomplete_attempt_count=0,
            attempt_status=None,
            client_order_id=None,
            symbol=None,
            autonomous_entry_authorized=True,
            new_entry_blocked_by_recovery=False,
        )
    )

    status = await monitor.collect_status()
    assert status.balance == Decimal("321.50")
    assert status.global_discovery is not None
    assert status.global_discovery.interval is Interval.M1
    assert status.global_discovery.max_symbols == 20
    assert status.global_discovery.top_n == 5
    assert status.autonomous_live_recovery is not None
    assert status.autonomous_live_recovery.autonomous_entry_authorized
    output = StringIO()
    Console(file=output, force_terminal=False, width=180, height=60).print(
        monitor.render_dashboard(status)
    )
    rendered = output.getvalue()
    assert "Global Discovery" in rendered
    assert "1m" in rendered
    assert "Strategy Type" in rendered
    assert rendered.count("SUPERTREND") >= 2
    assert "U20/B-/T5" in rendered
    assert "321.50 USDT" in rendered
    assert "0 / 1" in rendered
    assert rendered.count("New LIVE Exposure") == 1
    assert "ENABLED - TESTNET" in rendered
    assert "Managed LIVE Positions" in rendered
    assert "NONE" in rendered
    assert "WAITING #1" in rendered
    assert "Next" in rendered


def test_terminal_recovery_block_prevents_enabled_entry_label() -> None:
    """Do not present autonomous entry as enabled during incomplete recovery."""
    asyncio.run(_run_terminal_recovery_block_test())


async def _run_terminal_recovery_block_test() -> None:
    """Render recovery as the dominant fail-closed entry gate."""
    health = LiveRuntimeHealthSnapshot(
        status=LiveRuntimeHealthStatus.ACTIVE,
        reason=None,
        contexts=(),
        affected_contexts=(),
        authorization_present=True,
        authorization_exact=True,
        runner_paused=False,
        cycle_in_progress=False,
        stream_states=(),
        monitor_states=(),
    )
    monitor = _create_monitor(
        trade_mode=TradeMode.LIVE,
        live_runtime_health=health,
        runtime_risk_limits=FakeRuntimeRiskLimitProvider(
            snapshot=RuntimeRiskLimits(
                max_open_positions=1,
                max_position_size_usdt=Decimal("5"),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_by="test",
            )
        ),
    )
    monitor.runtime_control.resume_global_cycle()
    monitor.autonomous_live_recovery_observability_service = FakeRecoveryProvider(
        snapshot=AutonomousLiveRecoverySnapshot(
            status=AutonomousLiveRecoveryStatus.POST_ENTRY_RECOVERY_REQUIRED,
            reason=AutonomousLiveRecoveryReason.ACKNOWLEDGED_UNCOMPLETED,
            incomplete_attempt_count=1,
            attempt_status=SubmissionAttemptStatus.ACKNOWLEDGED,
            client_order_id="btg-test",
            symbol="BEAMXUSDT",
            autonomous_entry_authorized=True,
            new_entry_blocked_by_recovery=True,
        )
    )

    status = await monitor.collect_status()
    output = StringIO()
    Console(file=output, force_terminal=False, width=180).print(
        monitor.render_dashboard(status)
    )
    rendered = output.getvalue()

    assert "New LIVE Exposure" in rendered
    assert "BLOCKED" in rendered
    assert "ENABLED - TESTNET" not in rendered


def test_terminal_runtime_capacity_tracks_current_durable_snapshot() -> None:
    """Refresh displayed capacity from the authoritative runtime-limit provider."""
    asyncio.run(_run_dynamic_runtime_capacity_test())


async def _run_dynamic_runtime_capacity_test() -> None:
    """Change a limit snapshot without rebuilding the terminal monitor."""
    health = LiveRuntimeHealthSnapshot(
        status=LiveRuntimeHealthStatus.ACTIVE,
        reason=None,
        contexts=(),
        affected_contexts=(),
        authorization_present=True,
        authorization_exact=True,
        runner_paused=False,
        cycle_in_progress=False,
        stream_states=(),
        monitor_states=(),
    )
    provider = FakeRuntimeRiskLimitProvider(
        snapshot=RuntimeRiskLimits(
            max_open_positions=1,
            max_position_size_usdt=Decimal("5"),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_by="test",
        )
    )
    monitor = _create_monitor(
        trade_mode=TradeMode.LIVE,
        live_runtime_health=health,
        runtime_risk_limits=provider,
    )
    first_status = await monitor.collect_status()
    first_output = StringIO()
    Console(file=first_output, force_terminal=False, width=180).print(
        monitor.render_dashboard(first_status)
    )
    assert "0 / 1" in first_output.getvalue()

    provider.snapshot = replace(
        provider.snapshot,
        max_open_positions=2,
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        updated_by="telegram:test",
    )
    second_status = await monitor.collect_status()
    second_output = StringIO()
    Console(file=second_output, force_terminal=False, width=180).print(
        monitor.render_dashboard(second_status)
    )
    assert "0 / 2" in second_output.getvalue()


def test_terminal_stale_single_context_health_survives_multi_context_transition() -> (
    None
):
    """Do not read singular runtime accessors after an async context transition."""
    asyncio.run(_run_terminal_stale_health_transition_test())


async def _run_terminal_stale_health_transition_test() -> None:
    """Reproduce a stale health snapshot racing with multi-context adoption."""
    first_context = LiveRuntimePositionContext(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_CROSS,
    )
    second_context = LiveRuntimePositionContext(
        symbol="ETHUSDT",
        interval=Interval.M5,
        strategy_type=StrategyType.EMA_SCALPING,
    )
    stale_health = LiveRuntimeHealthSnapshot(
        status=LiveRuntimeHealthStatus.ACTIVE,
        reason=None,
        contexts=(first_context,),
        affected_contexts=(),
        authorization_present=True,
        authorization_exact=True,
        runner_paused=False,
        cycle_in_progress=False,
        stream_states=(),
        monitor_states=(),
    )
    control = TradingRuntimeControl(symbol="BTCUSDT")
    control.set_stream_enabled(True)
    control.record_stream_tick(price=Decimal("110"))
    monitor = _create_monitor(
        runtime_control=control,
        trade_mode=TradeMode.LIVE,
        live_runtime_health=stale_health,
    )
    monitor.position_provider = TransitioningPositionProvider(
        runtime_control=control,
        positions=(_create_position(),),
        contexts=(first_context, second_context),
    )

    status = await monitor.collect_status()

    assert len(control.runtime_contexts) == 2
    assert status.live_runtime_health == stale_health
    assert status.unrealized_pnl == Decimal("2")


def test_terminal_multi_context_health_never_selects_a_singular_runtime() -> None:
    """Render complete read-only LIVE health without touching legacy accessors."""
    asyncio.run(_run_terminal_multi_context_health_test())


async def _run_terminal_multi_context_health_test() -> None:
    """Collect and render an ambiguous runtime portfolio safely."""
    contexts = (
        LiveRuntimePositionContext(
            symbol="BTCUSDT",
            interval=Interval.M1,
            strategy_type=StrategyType.EMA_CROSS,
        ),
        LiveRuntimePositionContext(
            symbol="ETHUSDT",
            interval=Interval.M5,
            strategy_type=StrategyType.EMA_SCALPING,
        ),
    )
    health = LiveRuntimeHealthSnapshot(
        status=LiveRuntimeHealthStatus.DEGRADED,
        reason=LiveRuntimeHealthReason.MONITOR_UNHEALTHY,
        contexts=contexts,
        affected_contexts=(contexts[1],),
        authorization_present=True,
        authorization_exact=True,
        runner_paused=False,
        cycle_in_progress=False,
        stream_states=(),
        monitor_states=(
            LiveProtectionMonitorState(context=contexts[0], is_active=True),
            LiveProtectionMonitorState(
                context=contexts[1],
                is_active=True,
                failure_type="RuntimeError",
            ),
        ),
    )
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=contexts)
    monitor = _create_monitor(
        runtime_control=control,
        positions=(_create_position(),),
        live_runtime_health=health,
        trade_mode=TradeMode.LIVE,
    )

    status = await monitor.collect_status()
    compact = await monitor.refresh()
    output = StringIO()
    Console(file=output, force_terminal=False, width=140).print(
        monitor.render_dashboard(status)
    )
    rendered = output.getvalue()

    assert status.unrealized_pnl == Decimal("2")
    assert "contexts=2" in compact
    assert "BTCUSDT" in rendered
    assert "ETHUSDT" in rendered
    assert "Health" in rendered
    assert "STREAM WAIT" in rendered
    assert "Management Reason" in rendered
    assert "New LIVE Exposure" in rendered


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

    assert "Runtime & Safety" in rendered
    assert "Managed LIVE Positions" in rendered
    assert "Log Messages" in rendered
    assert "PAPER" in rendered
    assert len(monitor.log_handler.get_entries()) == 1
    assert "Qty" in rendered
    assert "Entry" in rendered and "Mark" in rendered
    assert "Trading Performance" in rendered
    assert "PAPER PORTFOLIO" in rendered
    assert "Step" in rendered
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
        (1.0, -1.0, "balance refresh interval"),
    ),
)
def test_terminal_monitor_rejects_invalid_intervals(
    refresh_interval: float,
    live_balance_interval: float,
    message: str,
) -> None:
    """Reject invalid terminal and exchange refresh intervals."""
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


def test_terminal_merges_realtime_position_without_losing_protection_fields() -> None:
    """Overlay streamed exposure while retaining the durable position metadata."""
    asyncio.run(_run_terminal_realtime_position_overlay_test())


async def _run_terminal_realtime_position_overlay_test() -> None:
    """Collect a public terminal snapshot with private position updates."""
    position = _live_position("BTCUSDT")
    snapshot = LiveFuturesUserDataSnapshot(
        status=LiveFuturesUserDataStatus.READY,
        last_event_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        last_snapshot_at=datetime(2026, 1, 1, tzinfo=UTC),
        balances=(),
        positions=(),
        position_updates=(
            FuturesUserDataPositionUpdate(
                symbol="BTCUSDT",
                quantity=Decimal("2"),
                entry_price=Decimal("102"),
                unrealized_pnl=Decimal("5"),
            ),
        ),
        recent_orders=(),
    )
    monitor = _create_monitor(
        positions=(position,),
        trade_mode=TradeMode.LIVE,
    )
    monitor.live_futures_user_data_service = FakeLiveFuturesUserDataProvider(
        snapshot=snapshot,
    )

    status = await monitor.collect_status()

    assert status.positions[0].quantity == Decimal("2")
    assert status.positions[0].entry_price == Decimal("102")
    assert status.positions[0].unrealized_pnl == Decimal("5")
    assert status.positions[0].stop_loss == position.stop_loss


# =============================================================================
# LIVE 0/1/N Correlation Regressions
# =============================================================================
def _live_position(
    symbol: str,
    *,
    side: PositionSide = PositionSide.LONG,
    entry: str = "100",
    current: str = "101",
) -> Position:
    """Create one metadata-complete position for managed LIVE rendering."""
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    return Position(
        symbol=symbol,
        side=side,
        quantity=Decimal("1"),
        entry_price=Decimal(entry),
        current_price=Decimal(current),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=observed_at,
        updated_at=observed_at,
        stop_loss=Decimal("90"),
        take_profit=Decimal("120"),
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_CROSS,
    )


def _live_context(symbol: str) -> LiveRuntimePositionContext:
    return LiveRuntimePositionContext(
        symbol=symbol,
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_CROSS,
    )


def _live_health(
    contexts: tuple[LiveRuntimePositionContext, ...],
    *,
    stream_states: tuple[LiveMarketStreamState, ...] = (),
    monitor_states: tuple[LiveProtectionMonitorState, ...] = (),
    exact: bool = True,
) -> LiveRuntimeHealthSnapshot:
    has_contexts = bool(contexts)
    return LiveRuntimeHealthSnapshot(
        status=(
            LiveRuntimeHealthStatus.ACTIVE
            if has_contexts
            else LiveRuntimeHealthStatus.INACTIVE
        ),
        reason=None if has_contexts else LiveRuntimeHealthReason.NO_POSITIONS,
        contexts=contexts,
        affected_contexts=(),
        authorization_present=exact,
        authorization_exact=exact,
        runner_paused=False,
        cycle_in_progress=False,
        stream_states=stream_states,
        monitor_states=monitor_states,
    )


def _live_stream(symbol: str, price: str) -> LiveMarketStreamState:
    return LiveMarketStreamState(
        identity=LiveMarketStreamIdentity(symbol=symbol, interval=Interval.M1),
        lifecycle_status=LiveMarketStreamLifecycleStatus.RUNNING,
        first_tick_received=True,
        event_count=1,
        last_price=Decimal(price),
        last_event_monotonic=1.0,
    )


def _render_live(
    *,
    positions: tuple[Position, ...],
    health: LiveRuntimeHealthSnapshot,
    paused: bool = False,
    max_open_positions: int | None = None,
) -> str:
    """Render one deterministic LIVE dashboard frame."""
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=health.contexts)
    if not paused:
        control.resume_global_cycle()
    monitor = _create_monitor(
        runtime_control=control,
        positions=positions,
        trade_mode=TradeMode.LIVE,
        live_runtime_health=health,
        live_balance=FakeLiveBalanceProvider(balance=Decimal("500")),
    )
    monitor.autonomous_live_recovery_observability_service = FakeRecoveryProvider(
        snapshot=AutonomousLiveRecoverySnapshot(
            status=AutonomousLiveRecoveryStatus.CLEAR,
            reason=None,
            incomplete_attempt_count=0,
            attempt_status=None,
            client_order_id=None,
            symbol=None,
            autonomous_entry_authorized=True,
            new_entry_blocked_by_recovery=False,
        )
    )
    monitor.max_open_positions = max_open_positions
    status = asyncio.run(monitor.collect_status())
    output = StringIO()
    Console(file=output, force_terminal=False, width=170, height=50).print(
        monitor.render_dashboard(status)
    )
    return output.getvalue()


def test_paper_monitor_ignores_injected_live_health_provider() -> None:
    """Preserve legacy PAPER status and stream rendering under production wiring."""
    context = _live_context("BTCUSDT")
    health_provider = CountingLiveRuntimeHealthProvider(
        snapshot=_live_health(
            (context,),
            stream_states=(_live_stream("BTCUSDT", "999"),),
            monitor_states=(
                LiveProtectionMonitorState(context=context, is_active=True),
            ),
        )
    )
    control = TradingRuntimeControl(symbol="BTCUSDT")
    control.set_stream_enabled(True)
    control.record_stream_tick(price=Decimal("110"))
    monitor = _create_monitor(
        runtime_control=control,
        paper_balance=FakePaperBalanceProvider(
            balance=Decimal("10000"),
            realized_pnl=Decimal("46.925025"),
        ),
        positions=(_create_position(),),
        trade_mode=TradeMode.PAPER,
    )
    monitor.live_runtime_health_service = health_provider

    status = asyncio.run(monitor.collect_status())
    output = StringIO()
    Console(file=output, force_terminal=False, width=180, height=60).print(
        monitor.render_dashboard(status)
    )
    rendered = output.getvalue()

    assert health_provider.calls == 0
    assert status.live_runtime_health is None
    assert status.balance == Decimal("10000")
    assert status.realized_pnl == Decimal("46.925025")
    assert status.unrealized_pnl == Decimal("20")
    assert "Runtime & Safety" in rendered
    assert "Managed LIVE Positions" in rendered
    assert "PAPER" in rendered


def test_terminal_zero_managed_positions_dashboard_is_explicit_and_safe() -> None:
    """Render autonomous zero-position LIVE state without requiring authorization."""
    health = _live_health((), exact=False)
    rendered = _render_live(positions=(), health=health)
    assert "Runtime & Safety" in rendered
    assert "Managed LIVE Positions" in rendered
    assert "Global Discovery" in rendered
    assert "Runtime Events" in rendered or "Log Messages" in rendered
    assert "Global Runner" in rendered
    assert "RUNNING" in rendered
    assert "Position Management" in rendered
    assert "INACTIVE" in rendered
    assert "Portfolio" in rendered
    assert "0" in rendered
    assert "Authorization Coverage" in rendered
    assert "Protection Gate" in rendered
    assert "READY" in rendered
    assert "NONE" in rendered


def test_terminal_paused_zero_position_blocks_new_exposure() -> None:
    """A paused empty portfolio must not display enabled exposure."""
    rendered = _render_live(
        positions=(), health=_live_health((), exact=False), paused=True
    )
    assert "Global Runner" in rendered
    assert "PAUSED" in rendered
    assert "New LIVE Exposure" in rendered
    assert "BLOCKED" in rendered
    assert "ENABLED - TESTNET" not in rendered


def test_terminal_one_managed_position_renders_exact_correlation() -> None:
    """Render one position with its matching stream, monitor, and authorization."""
    context = _live_context("BTCUSDT")
    rendered = _render_live(
        positions=(_live_position("BTCUSDT"),),
        health=_live_health(
            (context,),
            stream_states=(_live_stream("BTCUSDT", "110"),),
            monitor_states=(
                LiveProtectionMonitorState(context=context, is_active=True),
            ),
        ),
    )
    for text in (
        "BTCUSDT",
        "LONG",
        "Qty",
        "Entry",
        "Mark",
        "SL",
        "TP",
        "Step",
        "Health",
        "100",
        "OK",
        "Health",
        "Authorization Coverage",
    ):
        assert text in rendered
    assert "\\n" not in rendered


def test_terminal_two_managed_positions_correlate_by_symbol() -> None:
    """Render two symbols without singular runtime-control access."""
    contexts = (_live_context("BTCUSDT"), _live_context("ETHUSDT"))
    rendered = _render_live(
        positions=(
            _live_position("BTCUSDT"),
            _live_position("ETHUSDT", entry="200", current="180"),
        ),
        health=_live_health(
            contexts,
            stream_states=(
                _live_stream("BTCUSDT", "110"),
                _live_stream("ETHUSDT", "180"),
            ),
            monitor_states=tuple(
                LiveProtectionMonitorState(context=context, is_active=True)
                for context in contexts
            ),
        ),
    )
    assert "BTCUSDT" in rendered and "ETHUSDT" in rendered
    assert "Mark" in rendered and "180" in rendered
    assert "Balance" in rendered
    assert "500.00 USDT" in rendered
    assert "Unrealized PnL" in rendered
    assert "-10.00 USDT" in rendered
    assert rendered.count("Authorization Coverage") == 1


def test_terminal_three_managed_positions_render_without_omission() -> None:
    """Render all three managed contexts in the bounded LIVE panel."""
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    contexts = tuple(_live_context(symbol) for symbol in symbols)
    rendered = _render_live(
        positions=tuple(_live_position(symbol) for symbol in symbols),
        health=_live_health(
            contexts,
            stream_states=tuple(_live_stream(symbol, "110") for symbol in symbols),
            monitor_states=tuple(
                LiveProtectionMonitorState(context=context, is_active=True)
                for context in contexts
            ),
        ),
    )
    for symbol in symbols:
        assert symbol in rendered


def test_terminal_five_managed_positions_fit_compact_dashboard() -> None:
    """Render every configured managed position at the required terminal size."""
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT")
    contexts = tuple(_live_context(symbol) for symbol in symbols)
    rendered = _render_live(
        positions=tuple(_live_position(symbol) for symbol in symbols),
        health=_live_health(
            contexts,
            stream_states=tuple(_live_stream(symbol, "110") for symbol in symbols),
            monitor_states=tuple(
                LiveProtectionMonitorState(context=context, is_active=True)
                for context in contexts
            ),
        ),
        max_open_positions=5,
    )

    assert "Symbol" in rendered and "Health" in rendered
    assert all(symbol in rendered for symbol in symbols)
    assert rendered.count("OK") == 5


def test_terminal_multi_position_pnl_is_exact_and_symbol_matched() -> None:
    """Use 110 for BTC long and 180 for ETH short, totaling exactly 30."""
    contexts = (_live_context("BTCUSDT"), _live_context("ETHUSDT"))
    positions = (
        _live_position("BTCUSDT", entry="100"),
        _live_position("ETHUSDT", side=PositionSide.SHORT, entry="200", current="190"),
    )
    health = _live_health(
        contexts,
        stream_states=(_live_stream("BTCUSDT", "110"), _live_stream("ETHUSDT", "180")),
        monitor_states=tuple(
            LiveProtectionMonitorState(context=context, is_active=True)
            for context in contexts
        ),
    )
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=contexts)
    monitor = _create_monitor(
        runtime_control=control,
        positions=positions,
        trade_mode=TradeMode.LIVE,
        live_runtime_health=health,
    )
    assert asyncio.run(monitor.collect_status()).unrealized_pnl == Decimal("30")


def test_terminal_mixed_stream_pnl_falls_back_per_symbol() -> None:
    """Use A's ready stream and B's persisted mark independently."""
    contexts = (_live_context("BTCUSDT"), _live_context("ETHUSDT"))
    positions = (
        _live_position("BTCUSDT", entry="100", current="101"),
        _live_position("ETHUSDT", side=PositionSide.SHORT, entry="200", current="190"),
    )
    failed_eth = replace(
        _live_stream("ETHUSDT", "180"),
        first_tick_received=False,
        lifecycle_status=LiveMarketStreamLifecycleStatus.FAILED,
        last_price=None,
    )
    health = _live_health(
        contexts,
        stream_states=(_live_stream("BTCUSDT", "110"), failed_eth),
        monitor_states=tuple(
            LiveProtectionMonitorState(context=context, is_active=True)
            for context in contexts
        ),
    )
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=contexts)
    monitor = _create_monitor(
        runtime_control=control,
        positions=positions,
        trade_mode=TradeMode.LIVE,
        live_runtime_health=health,
    )
    assert asyncio.run(monitor.collect_status()).unrealized_pnl == Decimal("20")


def test_terminal_context_without_local_position_shows_divergence_and_blocks() -> None:
    """Never fabricate managed position fields for a missing local position."""
    context = _live_context("BTCUSDT")
    rendered = _render_live(
        positions=(),
        health=_live_health(
            (context,),
            stream_states=(_live_stream("BTCUSDT", "110"),),
            monitor_states=(
                LiveProtectionMonitorState(context=context, is_active=True),
            ),
        ),
    )
    assert "POSITION MISSING" in rendered
    assert "qty=" not in rendered
    assert "New LIVE Exposure" in rendered and "BLOCKED" in rendered


def test_terminal_unmanaged_local_position_is_visible_and_blocked() -> None:
    """Show local exposure as unmanaged rather than as a healthy managed row."""
    rendered = _render_live(
        positions=(_live_position("BTCUSDT"),), health=_live_health((), exact=False)
    )
    assert "UNMANAGED EXPOSURE" in rendered
    assert "New LIVE Exposure" in rendered and "BLOCKED" in rendered
    assert "NONE" in rendered


def test_terminal_capacity_blocks_new_exposure() -> None:
    """Capacity blocks new exposure even when management ownership is exact."""
    context = _live_context("BTCUSDT")
    rendered = _render_live(
        positions=(_live_position("BTCUSDT"),),
        health=_live_health(
            (context,),
            stream_states=(_live_stream("BTCUSDT", "110"),),
            monitor_states=(
                LiveProtectionMonitorState(context=context, is_active=True),
            ),
        ),
        max_open_positions=1,
    )
    assert "New LIVE Exposure" in rendered
    assert "BLOCKED - CAPACITY" in rendered


def test_terminal_discovery_candidates_are_bounded_and_separate() -> None:
    """Keep safety rows visible while limiting discovery candidates to five."""
    telemetry = GlobalDiscoveryTelemetry(interval=Interval.M1, max_symbols=20, top_n=5)
    telemetry.begin_cycle(interval=Interval.M1)
    results = tuple(
        TradingResult(
            executed=False,
            decision=TradingDecision(
                should_execute=False,
                signal=Signal(
                    symbol=f"SYM{i}USDT",
                    signal_type=SignalType.BUY,
                    price=Decimal("100"),
                    confidence=Decimal("0.9"),
                    strategy_name="test",
                    generated_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                risk_result=None,
                reason="rejected",
            ),
            order=None,
            reason="rejected",
        )
        for i in range(8)
    )
    telemetry.complete_cycle(results=results)
    monitor = _create_monitor(
        trade_mode=TradeMode.LIVE, live_runtime_health=_live_health((), exact=False)
    )
    monitor.global_discovery_telemetry_provider = telemetry
    status = asyncio.run(monitor.collect_status())
    dashboard = monitor.render_dashboard(status)
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=200, height=100)
    console.print(dashboard)
    rendered = output.getvalue()
    safety_output = StringIO()
    Console(file=safety_output, force_terminal=False, width=100).print(
        dashboard["status"].renderable
    )
    safety = safety_output.getvalue()

    assert "Runtime & Safety" in rendered
    assert "Managed LIVE Positions" in rendered
    assert "Global Discovery" in rendered
    for index in range(5):
        assert f"SYM{index}USDT" in rendered
    for index in range(5, 8):
        assert f"SYM{index}USDT" not in rendered
    assert "SYM" not in safety
    assert "Recovered LIVE Streams" not in rendered


@dataclass(slots=True, kw_only=True)
class FakeLiveTradingPerformanceProvider:
    """Return a deterministic LIVE performance snapshot and count reads."""

    snapshot: TradingPerformanceSnapshot
    calls: int = 0

    async def get_snapshot(self) -> TradingPerformanceSnapshot:
        """Return the configured immutable aggregate."""
        self.calls += 1
        return self.snapshot


def test_terminal_live_performance_and_full_width_positions_render() -> None:
    """Render authoritative LIVE fills above the full-width event log."""
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT")
    contexts = tuple(_live_context(symbol) for symbol in symbols)
    health = _live_health(
        contexts,
        stream_states=tuple(_live_stream(symbol, "110") for symbol in symbols),
        monitor_states=tuple(
            LiveProtectionMonitorState(context=context, is_active=True)
            for context in contexts
        ),
    )
    monitor = _create_monitor(
        positions=tuple(_live_position(symbol) for symbol in symbols),
        trade_mode=TradeMode.LIVE,
        live_runtime_health=health,
        live_balance=FakeLiveBalanceProvider(balance=Decimal("500")),
    )
    performance_provider = FakeLiveTradingPerformanceProvider(
        snapshot=TradingPerformanceSnapshot(
            closed_trade_count=3,
            win_count=1,
            loss_count=1,
            break_even_count=1,
            realized_pnl=Decimal("3"),
            win_rate_percent=Decimal("33.33333333333333333333333333"),
        )
    )
    monitor.live_trading_performance_service = performance_provider
    monitor.max_open_positions = 5

    status = asyncio.run(monitor.collect_status())
    dashboard = monitor.render_dashboard(status)
    output = StringIO()
    Console(file=output, force_terminal=False, width=170, height=50).print(dashboard)
    rendered = output.getvalue()

    assert performance_provider.calls == 1
    assert status.trading_performance == performance_provider.snapshot
    assert tuple(child.name for child in dashboard.children) == (
        "summary",
        "managed_positions",
        "logs",
    )
    assert all(symbol in rendered for symbol in symbols)
    assert "Closed Trades" in rendered and "3" in rendered
    assert "Win / Loss" in rendered and "1 / 1" in rendered
    assert "33.3%" in rendered
    assert "+3.00 USDT" in rendered
    assert "BOTRAGRAM LIVE EXIT LEDGER" in rendered
    assert rendered.index("Managed LIVE Positions") < rendered.index(
        "Runtime Events | Log Messages"
    )
