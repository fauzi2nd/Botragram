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
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.runtime_control import (
    MarketStreamTelemetry,
    TradingRuntimeControl,
)
from botragram.engine import PnLEngine
from botragram.enums import TradeMode
from botragram.models import Position
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
        )

    def render_dashboard(self, status: TerminalStatus) -> Layout:
        """Build the three-panel Rich dashboard for one monitoring snapshot."""
        layout = Layout(name="root")
        layout.split_column(
            Layout(name="summary", size=16),
            Layout(name="logs", minimum_size=8),
        )
        layout["summary"].split_row(
            Layout(self._build_status_panel(status), name="status"),
            Layout(self._build_stream_panel(status), name="stream"),
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
    ) -> Decimal:
        """Calculate PnL using a fresh selected-symbol stream price when present."""
        total = _DECIMAL_ZERO

        for position in positions:
            stream_price = (
                stream.last_price
                if stream.enabled and position.symbol == self.runtime_control.symbol
                else None
            )
            total += self.pnl_engine.calculate_unrealized(
                position=position,
                current_price=stream_price,
            )

        return total

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
        """Build runtime, portfolio, and startup-gate details."""
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="bright_cyan", no_wrap=True)
        table.add_column(style="white")
        state = self._get_runtime_state(status)
        missing = ", ".join(status.missing_startup_requirements) or "READY"
        pnl_style = "green" if status.unrealized_pnl >= 0 else "red"
        realized_style = (
            "green"
            if status.realized_pnl is not None and status.realized_pnl >= 0
            else "red"
        )
        table.add_row("Runtime", Text(state, style=self._get_state_style(state)))
        table.add_row(
            "Exchange",
            f"{self.runtime_control.exchange_type.value.upper()} "
            f"({self.runtime_control.market_type.value.upper()})",
        )
        table.add_row("Mode", self.trade_mode.value)
        table.add_row("Symbol", self.runtime_control.symbol)
        table.add_row("Interval", self.runtime_control.interval.value)
        table.add_row("Strategy", self.runtime_control.strategy_type.value)
        table.add_row("Balance", f"{status.balance:,.2f} {self.quote_asset}")
        self._add_position_rows(table=table, status=status)
        table.add_row(
            "Unrealized PnL",
            Text(
                f"{status.unrealized_pnl:+,.2f} {self.quote_asset}",
                style=pnl_style,
            ),
        )
        table.add_row(
            "Realized PnL",
            Text(
                self._format_realized_pnl(status.realized_pnl),
                style=realized_style if status.realized_pnl is not None else "dim",
            ),
        )
        table.add_row("Startup Gate", missing)
        return Panel(
            table,
            title="[bold]Status & Portfolio[/bold]",
            border_style="cyan",
        )

    def _add_position_rows(
        self,
        *,
        table: Table,
        status: TerminalStatus,
    ) -> None:
        """Add selected-position direction and risk details to the panel."""
        position = self._get_display_position(status.positions)

        if position is None:
            table.add_row("Position (0)", "NONE")
            table.add_row("Entry / Mark", "-")
            table.add_row("Risk @ SL", "-")
            table.add_row("SL / TP", "-")
            return

        mark_price = self._get_position_mark_price(position=position, status=status)
        risk_amount = self._calculate_position_risk(position=position)
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

    def _build_stream_panel(self, status: TerminalStatus) -> Panel:
        """Build locally observed high-frequency stream telemetry."""
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="bright_magenta", no_wrap=True)
        table.add_column(style="white")
        health = self._get_stream_health(status)
        price = (
            f"{status.stream.last_price:,.8f}"
            if status.stream.last_price is not None
            else "WAITING"
        )
        age = (
            f"{status.stream_age_ms:,} ms" if status.stream_age_ms is not None else "-"
        )
        table.add_row("Health", Text(health, style=self._get_state_style(health)))
        table.add_row("Subscription", "ACTIVE" if status.stream.enabled else "INACTIVE")
        table.add_row("Symbol", self.runtime_control.symbol)
        table.add_row("Last Price", price)
        table.add_row("Tick Rate", f"{status.stream_rate:.2f} events/s")
        table.add_row("Last Tick Age", age)
        table.add_row("Events", f"{status.stream.event_count:,}")
        table.add_row("Dashboard", f"{1 / self.refresh_interval_seconds:.1f} refresh/s")
        return Panel(table, title="[bold]Market Stream[/bold]", border_style="magenta")

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

        return Panel(table, title="[bold]Log Messages[/bold]", border_style="blue")

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
