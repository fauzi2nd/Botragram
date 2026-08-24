"""
Botragram

Description:
    Periodic terminal portfolio and market-stream telemetry monitor.

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
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from typing import Final, Protocol

# =============================================================================
# Third Party Imports
# =============================================================================
from rich import box
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.global_discovery_telemetry import GlobalDiscoverySnapshot
from botragram.app.runtime_control import (
    MarketStreamTelemetry,
    TradingRuntimeControl,
)
from botragram.engine import PnLEngine
from botragram.enums import (
    LiveMarketStreamLifecycleStatus,
    LiveRuntimeHealthStatus,
    TradeMode,
)
from botragram.models import (
    AutonomousLiveRecoverySnapshot,
    LiveMarketStreamState,
    LiveRuntimeHealthSnapshot,
    LiveRuntimePositionContext,
    Position,
)
from botragram.services.live_trading_performance_service import (
    TradingPerformanceSnapshot,
)
from botragram.services.paper_trading_service import PaperPortfolioSnapshot

__all__ = [
    "DashboardLogEntry",
    "DashboardLogHandler",
    "TerminalMonitor",
    "TerminalStatus",
]


# =============================================================================
# Constants
# =============================================================================
_DEFAULT_REFRESH_INTERVAL_SECONDS: Final[float] = 0.25
_DEFAULT_LIVE_BALANCE_REFRESH_SECONDS: Final[float] = 10.0
_DEFAULT_LOG_CAPACITY: Final[int] = 200
_DISPLAYED_LOG_COUNT: Final[int] = 10
_STREAM_STALE_AFTER_MS: Final[int] = 3_000
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_APPLICATION_LOGGER_NAME: Final[str] = "botragram"


# =============================================================================
# Monitoring Contracts
# =============================================================================
class PaperBalanceProvider(Protocol):
    """Read reconstructed paper portfolio metrics."""

    async def get_portfolio_snapshot(self) -> PaperPortfolioSnapshot:
        """Return reconstructed paper balance and realized PnL."""
        ...


class LiveBalanceProvider(Protocol):
    """Read normalized exchange balance."""

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return free exchange balance for one asset."""
        ...


class PositionSnapshotProvider(Protocol):
    """Read active positions for terminal monitoring."""

    async def get_open_positions(self) -> Sequence[Position]:
        """Return active positions."""
        ...


class LiveRuntimeHealthProvider(Protocol):
    """Read immutable recovered LIVE runtime health for presentation."""

    def get_snapshot(self) -> LiveRuntimeHealthSnapshot:
        """Return the current read-only operational health snapshot."""
        ...


class LiveTradingPerformanceProvider(Protocol):
    """Read cached authoritative LIVE realized performance."""

    async def get_snapshot(self) -> TradingPerformanceSnapshot:
        """Return immutable aggregate of recent realized Futures fills."""
        ...


class AutonomousLiveRecoveryObservabilityProvider(Protocol):
    """Read durable autonomous recovery state for terminal presentation."""

    async def get_snapshot(self) -> AutonomousLiveRecoverySnapshot:
        """Return a read-only durable recovery snapshot."""
        ...


class GlobalDiscoveryTelemetryProvider(Protocol):
    """Read local global-discovery telemetry without exchange I/O."""

    def get_global_discovery_snapshot(self) -> GlobalDiscoverySnapshot | None:
        """Return an immutable process-local discovery snapshot."""
        ...


type TerminalOutput = Callable[[str], None]


# =============================================================================
# Monitoring Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class TerminalStatus:
    """Immutable terminal monitoring snapshot."""

    observed_at: datetime
    balance: Decimal
    position_count: int
    unrealized_pnl: Decimal
    stream: MarketStreamTelemetry
    stream_rate: float
    stream_age_ms: int | None
    missing_startup_requirements: tuple[str, ...]
    realized_pnl: Decimal | None = None
    positions: tuple[Position, ...] = ()
    live_runtime_health: LiveRuntimeHealthSnapshot | None = None
    trading_performance: TradingPerformanceSnapshot | None = None
    autonomous_live_recovery: AutonomousLiveRecoverySnapshot | None = None
    global_discovery: GlobalDiscoverySnapshot | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class DashboardLogEntry:
    """Immutable log event displayed by the terminal dashboard."""

    observed_at: datetime
    level_name: str
    logger_name: str
    message: str


class DashboardLogHandler(logging.Handler):
    """Keep a bounded, thread-safe snapshot of application log events."""

    def __init__(self, *, capacity: int = _DEFAULT_LOG_CAPACITY) -> None:
        """Initialize the bounded log buffer."""
        super().__init__()

        if capacity <= 0:
            raise ValueError("Dashboard log capacity must be greater than zero")

        self._entries: deque[DashboardLogEntry] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        """Capture one standard-library log record without terminal markup."""
        try:
            entry = DashboardLogEntry(
                observed_at=datetime.fromtimestamp(record.created, tz=UTC),
                level_name=record.levelname,
                logger_name=record.name,
                message=record.getMessage(),
            )
        except Exception:
            self.handleError(record)
            return

        self.acquire()

        try:
            self._entries.append(entry)
        finally:
            self.release()

    def get_entries(self) -> tuple[DashboardLogEntry, ...]:
        """Return an immutable snapshot of buffered log events."""
        self.acquire()

        try:
            return tuple(self._entries)
        finally:
            self.release()


# =============================================================================
# Terminal Monitor
# =============================================================================
@dataclass(slots=True, kw_only=True)
class TerminalMonitor:
    """Render portfolio, stream, and logs without extra exchange polling."""

    runtime_control: TradingRuntimeControl
    paper_balance_provider: PaperBalanceProvider
    live_balance_provider: LiveBalanceProvider
    position_provider: PositionSnapshotProvider
    pnl_engine: PnLEngine
    trade_mode: TradeMode
    quote_asset: str
    live_runtime_health_service: LiveRuntimeHealthProvider | None = None
    live_trading_performance_service: LiveTradingPerformanceProvider | None = None
    autonomous_live_recovery_observability_service: (
        AutonomousLiveRecoveryObservabilityProvider | None
    ) = None
    global_discovery_telemetry_provider: GlobalDiscoveryTelemetryProvider | None = None
    max_open_positions: int | None = None
    console: Console = field(default_factory=Console)
    log_handler: DashboardLogHandler = field(default_factory=DashboardLogHandler)
    output: TerminalOutput | None = None
    refresh_interval_seconds: float = _DEFAULT_REFRESH_INTERVAL_SECONDS
    live_balance_refresh_seconds: float = _DEFAULT_LIVE_BALANCE_REFRESH_SECONDS
    _cached_live_balance: Decimal | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _last_balance_refresh_monotonic: float = field(
        default=0.0,
        init=False,
        repr=False,
    )
    _previous_stream_count: int = field(default=0, init=False, repr=False)
    _previous_stream_sample_monotonic: float = field(
        default_factory=monotonic,
        init=False,
        repr=False,
    )
    _stop_event: asyncio.Event = field(
        default_factory=asyncio.Event,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Normalize labels and validate refresh intervals."""
        self.quote_asset = self.quote_asset.strip().upper()

        if not self.quote_asset:
            raise ValueError("Terminal monitor quote asset must not be empty")

        if self.refresh_interval_seconds <= 0:
            raise ValueError("Terminal refresh interval must be greater than zero")

        if self.live_balance_refresh_seconds <= 0:
            raise ValueError("Live balance refresh interval must be greater than zero")

        if self.max_open_positions is not None and self.max_open_positions <= 0:
            raise ValueError("Terminal maximum open positions must be positive")

    async def run(self) -> None:
        """Render the Rich dashboard until graceful shutdown is requested."""
        self._stop_event.clear()
        application_logger = logging.getLogger(_APPLICATION_LOGGER_NAME)
        application_logger.addHandler(self.log_handler)
        suspended_handlers = self._suspend_console_handlers(
            logger=application_logger,
        )

        try:
            with Live(
                Text("Starting Botragram dashboard...", style="cyan"),
                console=self.console,
                auto_refresh=False,
                screen=True,
                redirect_stdout=False,
                redirect_stderr=False,
            ) as live:
                while not self._stop_event.is_set():
                    try:
                        status = await self.collect_status()
                        live.update(self.render_dashboard(status), refresh=True)

                        if self.output is not None:
                            self.output(self._render(status))
                    except Exception:
                        _LOGGER.exception("Terminal monitoring refresh failed")

                    await self._wait_for_refresh()
        finally:
            application_logger.removeHandler(self.log_handler)
            self._restore_console_handlers(suspended_handlers)

    async def refresh(self) -> str:
        """Collect, render, and emit one terminal monitoring snapshot."""
        status = await self.collect_status()
        line = self._render(status)

        if self.output is not None:
            self.output(line)

        return line

    async def collect_status(self) -> TerminalStatus:
        """Collect portfolio and stream metrics from existing local state."""
        sample_time = monotonic()
        stream = self.runtime_control.get_stream_telemetry()
        health_service = self.live_runtime_health_service
        live_runtime_health = (
            health_service.get_snapshot()
            if self.trade_mode is TradeMode.LIVE and health_service is not None
            else None
        )
        performance_service = self.live_trading_performance_service
        trading_performance: TradingPerformanceSnapshot | None = None
        if self.trade_mode is TradeMode.LIVE and performance_service is not None:
            try:
                trading_performance = await performance_service.get_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("LIVE trading performance refresh failed")
        recovery_service = self.autonomous_live_recovery_observability_service
        autonomous_live_recovery = (
            await recovery_service.get_snapshot()
            if recovery_service is not None
            else None
        )
        telemetry_provider = self.global_discovery_telemetry_provider
        global_discovery = (
            telemetry_provider.get_global_discovery_snapshot()
            if telemetry_provider is not None
            else None
        )
        positions = tuple(await self.position_provider.get_open_positions())
        balance, realized_pnl = await self._get_portfolio_metrics(
            sample_time=sample_time,
        )
        stream_rate = self._calculate_stream_rate(
            stream=stream,
            sample_time=sample_time,
        )

        return TerminalStatus(
            observed_at=datetime.now(UTC),
            balance=balance,
            position_count=len(positions),
            unrealized_pnl=self._calculate_unrealized_pnl(
                positions=positions,
                stream=stream,
                live_runtime_health=live_runtime_health,
            ),
            stream=stream,
            stream_rate=stream_rate,
            stream_age_ms=self._calculate_stream_age_ms(
                stream=stream,
                sample_time=sample_time,
            ),
            missing_startup_requirements=(
                self.runtime_control.get_missing_startup_requirements()
            ),
            realized_pnl=realized_pnl,
            positions=positions,
            live_runtime_health=live_runtime_health,
            trading_performance=trading_performance,
            autonomous_live_recovery=autonomous_live_recovery,
            global_discovery=global_discovery,
        )

    def render_dashboard(self, status: TerminalStatus) -> Layout:
        """Build a full-width managed-position dashboard for one snapshot."""
        managed_height = self._managed_positions_height(status)
        summary_height = 16 if status.global_discovery is not None else 14
        layout = Layout(name="root")
        layout.split_column(
            Layout(name="summary", size=summary_height),
            Layout(
                self._build_stream_panel(status),
                name="managed_positions",
                size=managed_height,
            ),
            Layout(name="logs", minimum_size=8),
        )
        layout["summary"].split_row(
            Layout(self._build_status_panel(status), name="status", ratio=1),
            Layout(self._build_performance_panel(status), name="performance"),
            Layout(self._build_discovery_panel(status), name="discovery"),
        )
        layout["logs"].update(self._build_log_panel())
        return layout

    def stop(self) -> None:
        """Request graceful terminal-monitor shutdown."""
        self._stop_event.set()

    async def _get_portfolio_metrics(
        self,
        *,
        sample_time: float,
    ) -> tuple[Decimal, Decimal | None]:
        """Return balance and an authoritative realized PnL when available."""
        if self.trade_mode is TradeMode.PAPER:
            snapshot = await self.paper_balance_provider.get_portfolio_snapshot()
            return snapshot.available_balance, snapshot.realized_pnl

        cached_balance = self._cached_live_balance
        cache_age = sample_time - self._last_balance_refresh_monotonic

        if cached_balance is not None and cache_age < self.live_balance_refresh_seconds:
            return cached_balance, None

        balance = await self.live_balance_provider.get_free_balance(
            asset=self.quote_asset,
        )
        self._cached_live_balance = balance
        self._last_balance_refresh_monotonic = sample_time
        return balance, None

    def _calculate_unrealized_pnl(
        self,
        *,
        positions: Sequence[Position],
        stream: MarketStreamTelemetry,
        live_runtime_health: LiveRuntimeHealthSnapshot | None,
    ) -> Decimal:
        """Calculate PnL using a fresh selected-symbol stream price when present."""
        total = _DECIMAL_ZERO
        can_use_legacy_singular_stream = live_runtime_health is None

        stream_states = (
            live_runtime_health.stream_states if live_runtime_health is not None else ()
        )
        for position in positions:
            stream_price = self._get_matching_stream_price(
                position=position,
                stream_states=stream_states,
            )
            if (
                stream_price is None
                and can_use_legacy_singular_stream
                and stream.enabled
                and position.symbol == self.runtime_control.symbol
            ):
                stream_price = stream.last_price
            total += self.pnl_engine.calculate_unrealized(
                position=position,
                current_price=stream_price,
            )

        return total

    @staticmethod
    def _get_matching_stream_price(
        *,
        position: Position,
        stream_states: Sequence[LiveMarketStreamState],
    ) -> Decimal | None:
        """Return a ready stream price only for the matching position symbol."""
        for state in stream_states:
            if state.identity.symbol != position.symbol:
                continue
            if (
                state.lifecycle_status is LiveMarketStreamLifecycleStatus.RUNNING
                and state.first_tick_received
                and state.last_price is not None
            ):
                return state.last_price
        return None

    def _calculate_stream_rate(
        self,
        *,
        stream: MarketStreamTelemetry,
        sample_time: float,
    ) -> float:
        """Calculate local stream events per second since the previous sample."""
        elapsed = sample_time - self._previous_stream_sample_monotonic
        event_delta = stream.event_count - self._previous_stream_count

        if event_delta < 0:
            event_delta = stream.event_count

        self._previous_stream_count = stream.event_count
        self._previous_stream_sample_monotonic = sample_time

        if elapsed <= 0:
            return 0.0

        return event_delta / elapsed

    @staticmethod
    def _calculate_stream_age_ms(
        *,
        stream: MarketStreamTelemetry,
        sample_time: float,
    ) -> int | None:
        """Return milliseconds since the most recent locally observed tick."""
        last_event = stream.last_event_monotonic

        if last_event is None:
            return None

        return max(0, round((sample_time - last_event) * 1_000))

    def _render(self, status: TerminalStatus) -> str:
        """Render one compact terminal telemetry line."""
        health = status.live_runtime_health
        recovery = status.autonomous_live_recovery
        if health is not None:
            timestamp = status.observed_at.strftime("%H:%M:%S.%f")[:-3]
            reason = health.reason.value if health.reason is not None else "NONE"
            authorization = "EXACT" if health.authorization_exact else "UNAVAILABLE"
            recovery_text = (
                f" recovery={recovery.status.value.upper()}"
                if recovery is not None
                else ""
            )
            return (
                f"[{timestamp}Z] BOTRAGRAM | health={health.status.value.upper()} "
                f"reason={reason.upper()} contexts={len(health.contexts)} "
                f"authorization={authorization} "
                f"batch={'BUSY' if health.cycle_in_progress else 'IDLE'}{recovery_text}"
            )
        state = "PAUSED" if self.runtime_control.is_paused else "RUNNING"
        cycle = "BUSY" if self.runtime_control.cycle_in_progress else "IDLE"
        stream_state = "ON" if status.stream.enabled else "OFF"
        price = (
            format(status.stream.last_price, "f")
            if status.stream.last_price is not None
            else "N/A"
        )
        age = f"{status.stream_age_ms}ms" if status.stream_age_ms is not None else "N/A"
        timestamp = status.observed_at.strftime("%H:%M:%S.%f")[:-3]

        return (
            f"[{timestamp}Z] BOTRAGRAM | state={state}/{cycle} "
            f"mode={self.trade_mode.value} symbol={self.runtime_control.symbol} "
            f"strategy={self.runtime_control.strategy_type.value} | "
            f"balance={status.balance:,.2f} {self.quote_asset} "
            f"positions={status.position_count} "
            f"pnl={status.unrealized_pnl:+,.2f} {self.quote_asset} "
            f"realized={self._format_realized_pnl(status.realized_pnl)} | "
            f"stream={stream_state} price={price} "
            f"rate={status.stream_rate:.1f}/s age={age} "
            f"events={status.stream.event_count}"
        )

    def _build_status_panel(self, status: TerminalStatus) -> Panel:
        """Build aggregate runtime and safety information without symbol duplication."""
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="bright_cyan", no_wrap=True)
        table.add_column(style="white")
        health = status.live_runtime_health
        if health is not None:
            table.add_row(
                "Global Runner",
                "PAUSED" if self.runtime_control.is_paused else "RUNNING",
            )
            table.add_row("Position Management", health.status.value.upper())
            if health.reason is not None:
                table.add_row("Management Reason", health.reason.value.upper())
            table.add_row("Portfolio", self._format_portfolio_capacity(status))
            if status.position_count != len(health.contexts):
                table.add_row("UNMANAGED EXPOSURE", "DETECTED")
            table.add_row(
                "Authorization Coverage",
                "EXACT" if health.authorization_exact else "UNAVAILABLE",
            )
            self._add_balance_and_unrealized_rows(table=table, status=status)
            table.add_row(
                "Protection Gate",
                "READY"
                if self.runtime_control.is_position_protection_ready
                else "CLOSED",
            )
            recovery = status.autonomous_live_recovery
            if recovery is not None:
                table.add_row("Autonomous Recovery", recovery.status.value.upper())
                if recovery.reason is not None:
                    table.add_row("Recovery Reason", recovery.reason.value.upper())
            self._add_autonomous_entry_row(table=table, status=status)
        else:
            table.add_row(
                "Global Runner",
                "PAUSED" if self.runtime_control.is_paused else "RUNNING",
            )
            table.add_row("Mode", self.trade_mode.value.upper())
            table.add_row("Portfolio", self._format_portfolio_capacity(status))
            self._add_balance_and_unrealized_rows(table=table, status=status)
            missing = ", ".join(status.missing_startup_requirements) or "READY"
            table.add_row("Startup Gate", missing)
        return Panel(
            table,
            title="[bold]Runtime & Safety[/bold]",
            border_style="cyan",
        )

    def _add_balance_and_unrealized_rows(
        self,
        *,
        table: Table,
        status: TerminalStatus,
    ) -> None:
        """Add aggregate balance and unrealized PnL safety metrics."""
        pnl_style = "green" if status.unrealized_pnl >= 0 else "red"
        table.add_row("Balance", f"{status.balance:,.2f} {self.quote_asset}")
        table.add_row(
            "Unrealized PnL",
            Text(
                f"{status.unrealized_pnl:+,.2f} {self.quote_asset}",
                style=pnl_style,
            ),
        )

    def _format_portfolio_capacity(self, status: TerminalStatus) -> str:
        """Format the actual and configured position capacity without symbols."""
        maximum = "-" if self.max_open_positions is None else self.max_open_positions
        return f"{status.position_count} / {maximum}"

    def _add_global_discovery_rows(
        self, *, table: Table, status: TerminalStatus
    ) -> None:
        """Add authoritative local global-discovery fields when configured."""
        discovery = status.global_discovery
        if discovery is None:
            return

        table.add_row("Execution Scope", "GLOBAL DISCOVERY")
        table.add_row("Market Interval", discovery.interval.value)
        table.add_row(
            "Discovery Cycle",
            f"{discovery.state.value.upper()} #{discovery.cycle_sequence}",
        )
        table.add_row("Discovery Bounds", self._format_discovery_bounds(discovery))
        table.add_row("Last Outcome", self._format_discovery_outcome(discovery))
        table.add_row("Rank Window", self._format_discovery_window(discovery))
        table.add_row(
            "Scanned",
            (
                str(discovery.scanned_count)
                if discovery.scanned_count is not None
                else "-"
            ),
        )
        table.add_row(
            "Candidates",
            str(discovery.actionable_count)
            if discovery.actionable_count is not None
            else "-",
        )
        if discovery.stopped_by_capacity:
            table.add_row("Capacity Stop", "YES")
        for candidate in discovery.candidates[:5]:
            outcome = candidate.outcome or "PENDING"
            table.add_row(
                "Candidate",
                f"{candidate.symbol} {candidate.direction.value.upper()} "
                f"confidence={candidate.confidence:f} outcome={outcome}",
            )
        if discovery.next_eligible_monotonic is not None:
            remaining = max(0, round(discovery.next_eligible_monotonic - monotonic()))
            table.add_row("Next Discovery", f"{remaining}s")

    @staticmethod
    def _format_discovery_bounds(discovery: GlobalDiscoverySnapshot) -> str:
        """Format ranked LIVE bounds while preserving legacy telemetry labels."""
        if discovery.universe_limit is not None and discovery.batch_size is not None:
            return (
                f"universe_limit={discovery.universe_limit} "
                f"batch_size={discovery.batch_size} top_n={discovery.top_n}"
            )
        return f"max_symbols={discovery.max_symbols} top_n={discovery.top_n}"

    @staticmethod
    def _format_discovery_outcome(discovery: GlobalDiscoverySnapshot) -> str:
        """Return a human-readable last cycle outcome."""
        outcome = discovery.last_outcome
        return outcome.value.upper().replace("_", " - ") if outcome is not None else "-"

    @staticmethod
    def _format_discovery_window(discovery: GlobalDiscoverySnapshot) -> str:
        """Return the exact ranked window for the last completed scan."""
        if (
            discovery.rank_start is None
            or discovery.rank_end is None
            or discovery.universe_size is None
        ):
            return "-"
        return (
            f"{discovery.rank_start}-{discovery.rank_end} / {discovery.universe_size}"
        )

    def _add_autonomous_entry_row(
        self, *, table: Table, status: TerminalStatus
    ) -> None:
        """Show authorization truthfully without exposing a capability."""
        recovery = status.autonomous_live_recovery
        health = status.live_runtime_health
        has_no_positions = status.position_count == 0 and (
            health is None or not health.contexts
        )
        has_capacity = (
            self.max_open_positions is None
            or status.position_count < self.max_open_positions
        )
        health_is_entry_safe = has_no_positions or (
            health is not None
            and health.status is LiveRuntimeHealthStatus.ACTIVE
            and health.authorization_present
            and health.authorization_exact
            and status.position_count == len(health.contexts)
        )
        entry_status = (
            "BLOCKED - CAPACITY"
            if not has_capacity
            else "ENABLED - TESTNET"
            if recovery is not None
            and recovery.autonomous_entry_authorized
            and not self.runtime_control.is_paused
            and self.runtime_control.is_position_protection_ready
            and health_is_entry_safe
            else "BLOCKED"
            if recovery is not None and recovery.autonomous_entry_authorized
            else "DISABLED"
        )
        table.add_row("New LIVE Exposure", entry_status)

    def _add_position_rows(
        self,
        *,
        table: Table,
        status: TerminalStatus,
    ) -> None:
        """Add selected-position direction and risk details to the panel."""
        position = self._get_display_position(status.positions)

        if position is None:
            if status.global_discovery is not None:
                maximum = (
                    "-"
                    if self.max_open_positions is None
                    else str(self.max_open_positions)
                )
                table.add_row(
                    "Portfolio",
                    f"positions=0 / max_open_positions={maximum}",
                )
            table.add_row("Position (0)", "NONE")
            table.add_row("Entry / Mark", "-")
            table.add_row("Risk @ SL", "-")
            table.add_row("SL / TP", "-")
            return

        mark_price = self._get_position_mark_price(position=position, status=status)
        risk_amount = self._calculate_position_risk(position=position)
        if status.global_discovery is not None:
            maximum = (
                "-" if self.max_open_positions is None else str(self.max_open_positions)
            )
            table.add_row(
                "Portfolio",
                f"positions={status.position_count} / max_open_positions={maximum}",
            )
        table.add_row(
            f"Position ({status.position_count})",
            f"{position.side.value.upper()} | Qty {position.quantity:f} | "
            f"{position.leverage}x",
        )
        table.add_row(
            "Entry / Mark",
            f"{position.entry_price:,.8f} / {mark_price:,.8f}",
        )
        table.add_row(
            "Risk @ SL",
            (
                f"{risk_amount:,.2f} {self.quote_asset}"
                if risk_amount is not None
                else "-"
            ),
        )
        table.add_row(
            "SL / TP",
            f"{self._format_optional_price(position.stop_loss)} / "
            f"{self._format_optional_price(position.take_profit)}",
        )

    def _get_display_position(
        self,
        positions: Sequence[Position],
    ) -> Position | None:
        """Return the selected-symbol position, or the first open position."""
        if len(self.runtime_control.runtime_contexts) > 1:
            return positions[0] if positions else None

        for position in positions:
            if position.symbol == self.runtime_control.symbol:
                return position

        return positions[0] if positions else None

    def _get_position_mark_price(
        self,
        *,
        position: Position,
        status: TerminalStatus,
    ) -> Decimal:
        """Return a fresh matching stream price or the persisted mark price."""
        if (
            status.stream.enabled
            and position.symbol == self.runtime_control.symbol
            and status.stream.last_price is not None
        ):
            return status.stream.last_price

        return position.current_price

    @staticmethod
    def _calculate_position_risk(*, position: Position) -> Decimal | None:
        """Return loss exposure at the configured stop-loss price."""
        if position.stop_loss is None:
            return None

        return abs(position.entry_price - position.stop_loss) * position.quantity

    @staticmethod
    def _format_optional_price(price: Decimal | None) -> str:
        """Format an optional portfolio protection price."""
        return f"{price:,.8f}" if price is not None else "-"

    def _format_realized_pnl(self, realized_pnl: Decimal | None) -> str:
        """Format realized PnL without inventing unavailable LIVE history."""
        if realized_pnl is None:
            return "N/A"

        return f"{realized_pnl:+,.2f} {self.quote_asset}"

    def _build_discovery_panel(self, status: TerminalStatus) -> Panel:
        """Build operator-focused bounded global-discovery telemetry."""
        discovery = status.global_discovery
        details = Table.grid(expand=True, padding=(0, 1))
        details.add_column(style="bright_yellow", no_wrap=True)
        details.add_column(style="white")
        if discovery is None:
            details.add_row("State", "NOT CONFIGURED")
            return Panel(
                details, title="[bold]Global Discovery[/bold]", border_style="yellow"
            )

        details.add_row(
            "State", f"{discovery.state.value.upper()} #{discovery.cycle_sequence}"
        )
        if discovery.last_outcome is not None:
            details.add_row(
                "Last Result",
                self._format_candidate_result(discovery.last_outcome.value),
            )
        details.add_row("Interval", discovery.interval.value)
        details.add_row("Window", self._format_discovery_window(discovery))
        details.add_row("Scope", self._format_discovery_scope(discovery))
        details.add_row(
            "Scanned",
            str(discovery.scanned_count)
            if discovery.scanned_count is not None
            else "-",
        )
        details.add_row(
            "Actionable",
            str(discovery.actionable_count)
            if discovery.actionable_count is not None
            else "-",
        )
        if discovery.stopped_by_capacity:
            details.add_row("Capacity", "REACHED")
        if discovery.next_eligible_monotonic is not None:
            remaining = max(0, round(discovery.next_eligible_monotonic - monotonic()))
            details.add_row("Next", f"{remaining}s")

        candidates = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False)
        candidates.add_column("Symbol", style="bright_magenta", no_wrap=True)
        candidates.add_column("Action", no_wrap=True)
        candidates.add_column("Score", justify="right", no_wrap=True)
        candidates.add_column("State", no_wrap=True)
        for candidate in discovery.candidates[:5]:
            candidates.add_row(
                candidate.symbol,
                candidate.direction.value.upper(),
                self._format_confidence(candidate.confidence),
                self._format_candidate_result(candidate.outcome),
            )
        return Panel(
            Group(details, candidates) if discovery.candidates else details,
            title="[bold]Global Discovery[/bold]",
            border_style="yellow",
        )

    @staticmethod
    def _format_discovery_scope(discovery: GlobalDiscoverySnapshot) -> str:
        """Format bounded scan scope without leaking telemetry field names."""
        universe = discovery.universe_limit or discovery.max_symbols
        parts = (
            f"U{universe}" if universe is not None else "U-",
            f"B{discovery.batch_size}" if discovery.batch_size is not None else "B-",
            f"T{discovery.top_n}" if discovery.top_n is not None else "T-",
        )
        return "/".join(parts)

    @staticmethod
    def _format_candidate_result(outcome: str | None) -> str:
        """Present a discovery outcome without internal snake-case labels."""
        labels = {
            "blocked_by_capacity": "CAPACITY",
            "entry_blocked": "BLOCKED",
            "executed_and_protected": "LIVE",
            "no_signal": "NO SIGNAL",
            "risk_rejected": "RISK REJECT",
            "skipped_capacity": "CAPACITY",
            "venue_rule_rejected": "VENUE REJECT",
        }
        if outcome is None:
            return "PENDING"
        normalized = outcome.strip().lower()
        return labels.get(normalized, normalized.upper().replace("_", " "))

    @staticmethod
    def _format_confidence(confidence: Decimal) -> str:
        """Present normalized confidence with four significant percentage digits."""
        percentage = confidence * Decimal("100")
        if percentage.is_zero():
            return "0%"

        quantum = Decimal("1").scaleb(percentage.adjusted() - 3)
        return f"{percentage.quantize(quantum).normalize():f}%"

    def _build_performance_panel(self, status: TerminalStatus) -> Panel:
        """Build truthful PAPER or cached LIVE realized-performance telemetry."""
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="bright_green", no_wrap=True)
        table.add_column(style="white")
        if self.trade_mode is TradeMode.LIVE:
            self._add_live_performance_rows(table=table, status=status)
        else:
            table.add_row("Closed Trades", "N/A")
            table.add_row("Win / Loss", "N/A")
            table.add_row("Win Rate", "N/A")
            table.add_row(
                "Realized PnL", self._format_realized_pnl(status.realized_pnl)
            )
            table.add_row("Source", "PAPER PORTFOLIO")
        return Panel(
            table,
            title="[bold]Trading Performance[/bold]",
            border_style="green",
        )

    def _add_live_performance_rows(
        self,
        *,
        table: Table,
        status: TerminalStatus,
    ) -> None:
        """Add cached Futures fill performance or an explicit unavailable state."""
        performance = status.trading_performance
        if performance is None:
            table.add_row("Closed Trades", "N/A")
            table.add_row("Win / Loss", "N/A")
            table.add_row("Win Rate", "N/A")
            table.add_row("Realized PnL", "N/A")
            table.add_row("Source", "LIVE HISTORY UNAVAILABLE")
            return
        table.add_row("Closed Trades", str(performance.closed_trade_count))
        table.add_row(
            "Win / Loss",
            f"{performance.win_count} / {performance.loss_count}",
        )
        table.add_row("Win Rate", f"{performance.win_rate_percent:.1f}%")
        table.add_row(
            "Realized PnL",
            f"{performance.realized_pnl:+,.2f} {self.quote_asset}",
        )
        table.add_row("Source", "LIVE FUTURES ACCOUNT FILLS")

    def _build_stream_panel(self, status: TerminalStatus) -> Panel:
        """Build one compact, canonical row for every managed position."""
        table = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False)
        table.add_column("Symbol", style="bright_magenta", no_wrap=True)
        table.add_column("Side", no_wrap=True)
        table.add_column("Qty", justify="right", no_wrap=True)
        table.add_column("Entry", justify="right", no_wrap=True)
        table.add_column("Mark", justify="right", no_wrap=True)
        table.add_column("SL", justify="right", no_wrap=True)
        table.add_column("TP", justify="right", no_wrap=True)
        table.add_column("Step", justify="right", no_wrap=True)
        table.add_column("Health", no_wrap=True)
        health_snapshot = status.live_runtime_health
        if health_snapshot is None:
            self._add_paper_position_rows(table=table, status=status)
        elif not health_snapshot.contexts:
            table.add_row("-", "-", "-", "-", "-", "-", "-", "-", "NONE")
        else:
            for context in health_snapshot.contexts:
                position = next(
                    (
                        item
                        for item in status.positions
                        if item.symbol == context.symbol
                    ),
                    None,
                )
                self._add_managed_position_row(
                    table=table,
                    position=position,
                    context=context,
                    health_snapshot=health_snapshot,
                )
        return Panel(
            table,
            title="[bold]Managed LIVE Positions[/bold]",
            border_style="magenta",
        )

    def _add_paper_position_rows(self, *, table: Table, status: TerminalStatus) -> None:
        """Render paper positions in the same compact canonical table."""
        if not status.positions:
            table.add_row("-", "-", "-", "-", "-", "-", "-", "-", "NONE")
            return
        for position in status.positions:
            table.add_row(
                position.symbol,
                position.side.value.upper(),
                self._format_compact_decimal(position.quantity),
                self._format_compact_decimal(position.entry_price),
                self._format_compact_decimal(position.current_price),
                self._format_compact_price(position.stop_loss),
                self._format_compact_price(position.take_profit),
                str(position.protection_step),
                "PAPER",
            )

    def _add_managed_position_row(
        self,
        *,
        table: Table,
        position: Position | None,
        context: LiveRuntimePositionContext,
        health_snapshot: LiveRuntimeHealthSnapshot,
    ) -> None:
        """Render one exact context with its correlated position and health."""
        if position is None:
            table.add_row(
                context.symbol,
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "POSITION MISSING",
            )
            return
        mark = (
            self._get_matching_stream_price(
                position=position,
                stream_states=health_snapshot.stream_states,
            )
            or position.current_price
        )
        table.add_row(
            context.symbol,
            position.side.value.upper(),
            self._format_compact_decimal(position.quantity),
            self._format_compact_decimal(position.entry_price),
            self._format_compact_decimal(mark),
            self._format_compact_price(position.stop_loss),
            self._format_compact_price(position.take_profit),
            str(position.protection_step),
            self._get_managed_position_health(
                context=context,
                health_snapshot=health_snapshot,
            ),
        )

    @staticmethod
    def _format_compact_decimal(value: Decimal) -> str:
        """Format a Decimal with stable precision and no representation noise."""
        if value.is_zero():
            return "0"
        quantum = Decimal("1").scaleb(value.adjusted() - 7)
        return format(value.quantize(quantum).normalize(), "f")

    def _format_compact_price(self, price: Decimal | None) -> str:
        """Format an optional protection trigger for a compact table column."""
        return self._format_compact_decimal(price) if price is not None else "-"

    @staticmethod
    def _get_managed_position_health(
        *,
        context: LiveRuntimePositionContext,
        health_snapshot: LiveRuntimeHealthSnapshot,
    ) -> str:
        """Classify one context from the existing health snapshot only."""
        stream_state = next(
            (
                state
                for state in health_snapshot.stream_states
                if state.identity.symbol == context.symbol
                and state.identity.interval == context.interval
            ),
            None,
        )
        if (
            stream_state is None
            or stream_state.lifecycle_status
            is not LiveMarketStreamLifecycleStatus.RUNNING
            or not stream_state.first_tick_received
        ):
            return "STREAM WAIT"
        monitor_state = next(
            (
                state
                for state in health_snapshot.monitor_states
                if state.context == context
            ),
            None,
        )
        if (
            monitor_state is None
            or not monitor_state.is_active
            or monitor_state.failure_type is not None
        ):
            return "MONITOR FAIL"
        if not health_snapshot.authorization_exact:
            return "AUTH MISSING"
        return "OK"

    def _managed_positions_height(self, status: TerminalStatus) -> int:
        """Reserve enough rows for all expected compact position table rows."""
        context_count = (
            len(status.live_runtime_health.contexts)
            if status.live_runtime_health is not None
            else len(status.positions)
        )
        capacity = self.max_open_positions if self.max_open_positions is not None else 0
        return max(7, max(context_count, capacity, 1) + 5)

    def _build_log_panel(self) -> Panel:
        """Build the bounded application-log table."""
        table = Table(
            box=box.SIMPLE_HEAD,
            expand=True,
            show_edge=False,
            pad_edge=False,
        )
        table.add_column("Timestamp", width=12, no_wrap=True, style="bright_cyan")
        table.add_column("Level", width=9, no_wrap=True)
        table.add_column("Event", ratio=1, no_wrap=True)
        table.add_column("Details", ratio=3, overflow="fold")
        entries = self.log_handler.get_entries()[-_DISPLAYED_LOG_COUNT:]

        if not entries:
            table.add_row("-", "INFO", "dashboard", "Waiting for application logs...")
        else:
            for entry in entries:
                table.add_row(
                    entry.observed_at.strftime("%H:%M:%S.%f")[:-3],
                    Text(
                        entry.level_name,
                        style=self._get_log_level_style(entry.level_name),
                    ),
                    entry.logger_name.removeprefix("botragram."),
                    entry.message,
                )

        return Panel(
            table,
            title="[bold]Runtime Events | Log Messages[/bold]",
            border_style="blue",
        )

    def _get_runtime_state(self, status: TerminalStatus) -> str:
        """Return the runtime state shown in the status panel."""
        if not self.runtime_control.is_paused:
            return "RUNNING"

        if status.missing_startup_requirements:
            return "CONFIGURING"

        return "PAUSED / READY"

    @staticmethod
    def _get_stream_health(status: TerminalStatus) -> str:
        """Classify stream state from local event telemetry."""
        if not status.stream.enabled:
            return "OFF"

        if status.stream_age_ms is None:
            return "WAITING"

        if status.stream_age_ms > _STREAM_STALE_AFTER_MS:
            return "STALE"

        return "LIVE"

    @staticmethod
    def _get_state_style(state: str) -> str:
        """Return a consistent Rich style for runtime health labels."""
        if state in {"RUNNING", "LIVE", "PAUSED / READY"}:
            return "bold green"

        if state in {"CONFIGURING", "WAITING"}:
            return "bold yellow"

        return "bold red"

    @staticmethod
    def _get_log_level_style(level_name: str) -> str:
        """Return a Rich style for a standard logging level name."""
        return {
            "DEBUG": "dim",
            "INFO": "cyan",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold red",
        }.get(level_name, "white")

    def _suspend_console_handlers(
        self,
        *,
        logger: logging.Logger,
    ) -> tuple[tuple[logging.Handler, int], ...]:
        """Silence plain console handlers while retaining file logging."""
        suspended: list[tuple[logging.Handler, int]] = []

        for handler in logger.handlers:
            handler_type = type(handler)

            if not issubclass(handler_type, logging.StreamHandler):
                continue

            if issubclass(handler_type, logging.FileHandler):
                continue

            suspended.append((handler, handler.level))
            handler.setLevel(logging.CRITICAL + 1)

        return tuple(suspended)

    @staticmethod
    def _restore_console_handlers(
        suspended_handlers: Sequence[tuple[logging.Handler, int]],
    ) -> None:
        """Restore console handler levels after the dashboard exits."""
        for handler, level in suspended_handlers:
            handler.setLevel(level)

    async def _wait_for_refresh(self) -> None:
        """Wait for the next refresh while remaining immediately stoppable."""
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=self.refresh_interval_seconds,
            )
        except TimeoutError:
            return
