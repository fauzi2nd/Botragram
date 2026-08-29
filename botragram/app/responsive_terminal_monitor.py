"""
Botragram

Description:
    Width-aware Rich terminal dashboard presentation.

Python:
    3.14+
"""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from typing import Final

from rich import box
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from botragram.app.terminal_monitor import TerminalMonitor as BaseTerminalMonitor
from botragram.app.terminal_monitor import TerminalStatus
from botragram.enums import LiveFuturesUserDataStatus, TradeMode

__all__ = ["TerminalMonitor"]

_COMPACT_WIDTH: Final[int] = 90
_MEDIUM_WIDTH: Final[int] = 140
_CANDIDATE_EVENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Global discovery candidate processed: symbol=(?P<symbol>\S+) "
    r"side=(?P<side>\S+) confidence=(?P<confidence>\S+) "
    r"outcome=(?P<outcome>\S+)"
)
_CYCLE_EVENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Global discovery cycle completed: outcome=(?P<outcome>\S+) "
    r"scanned=(?P<scanned>\d+) actionable=(?P<actionable>\d+) "
    r"rank_start=(?P<rank_start>\d+) rank_end=(?P<rank_end>\d+) "
    r"universe_size=(?P<universe_size>\d+) duration_ms=(?P<duration_ms>\d+)"
)
_NO_ENTRY_EVENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Trading cycle completed without execution: symbol=(?P<symbol>\S+) "
    r"reason=(?P<reason>\S+)"
)
_PREFLIGHT_EVENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Global discovery preflight started: interval=(?P<interval>\S+) "
    r"universe_limit=(?P<universe>\d+) batch_size=(?P<batch>\d+) "
    r"top_n=(?P<top_n>\d+)"
)
_HEARTBEAT_EVENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Runtime heartbeat: state=(?P<state>\S+) symbol=(?P<symbol>\S+) "
    r"strategy=(?P<strategy>\S+) stream=(?P<stream>\S+)"
)
_RUNNER_STARTED_EVENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Trading runner started: context_count=(?P<context_count>\d+) "
    r"mode=(?P<mode>\S+) candle_limit=(?P<candle_limit>\d+) "
    r"cycle_interval_override=(?P<cycle_interval_override>\S+)"
)


class TerminalMonitor(BaseTerminalMonitor):
    """Render the existing monitor data with width-aware Rich layouts."""

    async def collect_status(self) -> TerminalStatus:
        """Prefer authoritative private Futures PnL when that cache is ready."""
        status = await super().collect_status()
        user_data = status.live_futures_user_data
        if (
            self.trade_mode is not TradeMode.LIVE
            or user_data is None
            or user_data.status is not LiveFuturesUserDataStatus.READY
        ):
            return status

        authoritative_unrealized_pnl = sum(
            (update.unrealized_pnl for update in user_data.position_updates),
            start=Decimal("0"),
        )
        return replace(status, unrealized_pnl=authoritative_unrealized_pnl)

    def render_dashboard(self, status: TerminalStatus) -> Layout:
        """Choose a readable layout from the active terminal width."""
        width = self.console.size.width
        if width < _COMPACT_WIDTH:
            return self._render_compact_dashboard(status)
        if width < _MEDIUM_WIDTH:
            return self._render_medium_dashboard(status)
        return super().render_dashboard(status)

    def _render_medium_dashboard(self, status: TerminalStatus) -> Layout:
        """Use two summary columns and a full-width discovery panel."""
        managed_height = self._managed_positions_height(status)
        discovery_height = 15 if status.global_discovery is not None else 5
        layout = Layout(name="root")
        layout.split_column(
            Layout(name="summary", size=15),
            Layout(
                self._build_discovery_panel(status),
                name="discovery",
                size=discovery_height,
            ),
            Layout(
                self._build_stream_panel(status),
                name="managed_positions",
                size=managed_height,
            ),
            Layout(name="logs", minimum_size=8),
        )
        layout["summary"].split_row(
            Layout(self._build_status_panel(status), name="status"),
            Layout(self._build_performance_panel(status), name="performance"),
        )
        layout["logs"].update(self._build_log_panel())
        return layout

    def _render_compact_dashboard(self, status: TerminalStatus) -> Layout:
        """Prioritize safety, positions, and readable logs on portrait terminals."""
        layout = Layout(name="root")
        layout.split_column(
            Layout(
                self._build_compact_status_panel(status),
                name="status",
                size=self._compact_status_height(status),
            ),
            Layout(
                self._build_discovery_panel(status),
                name="discovery",
                size=self._compact_discovery_height(status),
            ),
            Layout(
                self._build_compact_performance_panel(status),
                name="performance",
                size=4,
            ),
            Layout(
                self._build_compact_positions_panel(status),
                name="managed_positions",
                size=self._compact_positions_height(status),
            ),
            Layout(
                self._build_compact_log_panel(status),
                name="logs",
                minimum_size=8,
            ),
        )
        return layout

    def _build_compact_status_panel(self, status: TerminalStatus) -> Panel:
        """Render safety state without duplicating discovery strategy metadata."""
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="bright_cyan", no_wrap=True)
        table.add_column(style="white")
        health = status.live_runtime_health

        table.add_row(
            "Global Runner",
            "PAUSED" if self.runtime_control.is_paused else "RUNNING",
        )
        if health is not None:
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

    def _build_compact_performance_panel(self, status: TerminalStatus) -> Panel:
        """Render the highest-value performance metrics in two portrait rows."""
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="bright_green", no_wrap=True)
        table.add_column(style="white")

        if self.trade_mode is TradeMode.LIVE:
            performance = status.trading_performance
            if performance is None:
                table.add_row("Trades / W-L", "N/A / N/A")
                table.add_row("Win Rate / PnL", "N/A / N/A")
            else:
                table.add_row(
                    "Trades / W-L",
                    f"{performance.closed_trade_count} / "
                    f"{performance.win_count}-{performance.loss_count}",
                )
                table.add_row(
                    "Win Rate / PnL",
                    f"{performance.win_rate_percent:.1f}% / "
                    f"{performance.realized_pnl:+,.2f} {self.quote_asset}",
                )
        else:
            table.add_row("Trades / W-L", "N/A / N/A")
            table.add_row(
                "Win Rate / PnL",
                f"N/A / {self._format_realized_pnl(status.realized_pnl)}",
            )

        return Panel(
            table,
            title="[bold]Trading Performance[/bold]",
            border_style="green",
        )

    def _build_compact_positions_panel(self, status: TerminalStatus) -> Panel:
        """Render up to five managed positions as portrait-friendly blocks."""
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="bright_magenta", no_wrap=True)
        table.add_column(style="white")
        health_snapshot = status.live_runtime_health

        if health_snapshot is None:
            if not status.positions:
                table.add_row("Positions", "NONE")
            else:
                for paper_position in status.positions:
                    self._add_compact_position_rows(
                        table=table,
                        symbol=paper_position.symbol,
                        side=paper_position.side.value.upper(),
                        leverage=paper_position.leverage,
                        quantity=self._format_compact_decimal(paper_position.quantity),
                        entry=self._format_compact_decimal(paper_position.entry_price),
                        mark=self._format_compact_decimal(paper_position.current_price),
                        pnl=self.format_position_pnl(paper_position.unrealized_pnl),
                        stop_loss=self._format_compact_price(paper_position.stop_loss),
                        take_profit=self._format_compact_price(
                            paper_position.take_profit
                        ),
                        step=paper_position.protection_step,
                        health="PAPER",
                    )
        elif not health_snapshot.contexts:
            table.add_row("Positions", "NONE")
        else:
            for context in health_snapshot.contexts:
                managed_position = next(
                    (
                        item
                        for item in status.positions
                        if item.symbol == context.symbol
                    ),
                    None,
                )
                if managed_position is None:
                    table.add_row(context.symbol, "POSITION MISSING")
                    continue
                mark = (
                    self._get_matching_stream_price(
                        position=managed_position,
                        stream_states=health_snapshot.stream_states,
                    )
                    or managed_position.current_price
                )
                self._add_compact_position_rows(
                    table=table,
                    symbol=context.symbol,
                    side=managed_position.side.value.upper(),
                    leverage=managed_position.leverage,
                    quantity=self._format_compact_decimal(managed_position.quantity),
                    entry=self._format_compact_decimal(managed_position.entry_price),
                    mark=self._format_compact_decimal(mark),
                    pnl=self.format_position_pnl(managed_position.unrealized_pnl),
                    stop_loss=self._format_compact_price(managed_position.stop_loss),
                    take_profit=self._format_compact_price(
                        managed_position.take_profit
                    ),
                    step=managed_position.protection_step,
                    health=self._get_managed_position_health(
                        context=context,
                        health_snapshot=health_snapshot,
                    ),
                )

        return Panel(
            table,
            title="[bold]Managed LIVE Positions[/bold]",
            border_style="magenta",
        )

    @staticmethod
    def _add_compact_position_rows(
        *,
        table: Table,
        symbol: str,
        side: str,
        leverage: int,
        quantity: str,
        entry: str,
        mark: str,
        pnl: str,
        stop_loss: str,
        take_profit: str,
        step: int,
        health: str,
    ) -> None:
        """Append one complete managed position in four portrait rows."""
        leverage_label = f"{leverage}x" if leverage > 0 else "N/A"
        table.add_row(symbol, f"{side} | {leverage_label} | {health} | STEP {step}")
        table.add_row("Qty / PnL", f"{quantity} / {pnl}")
        table.add_row("Entry / Mark", f"{entry} / {mark}")
        table.add_row("SL / TP", f"{stop_loss} / {take_profit}")

    def _build_compact_log_panel(self, status: TerminalStatus) -> Panel:
        """Use concise operator-facing events with a height-aware history limit."""
        table = Table(
            box=box.SIMPLE_HEAD,
            expand=True,
            show_edge=False,
            pad_edge=False,
        )
        table.add_column("Time", width=12, no_wrap=True, style="bright_cyan")
        table.add_column("Event", ratio=1, overflow="fold")
        entries = self.log_handler.get_entries()[-self._compact_log_limit(status) :]

        if not entries:
            table.add_row("-", "INFO | Waiting for application logs...")
        else:
            for entry in entries:
                level = Text(
                    entry.level_name,
                    style=self._get_log_level_style(entry.level_name),
                )
                details = Text.assemble(
                    level,
                    " | ",
                    self._format_compact_event(entry.message),
                )
                table.add_row(
                    entry.observed_at.strftime("%H:%M:%S.%f")[:-3],
                    details,
                )

        return Panel(
            table,
            title="[bold]Runtime Events[/bold]",
            border_style="blue",
        )

    @classmethod
    def _format_compact_event(cls, message: str) -> str:
        """Translate internal log syntax into concise operator-facing text."""
        candidate = _CANDIDATE_EVENT_PATTERN.fullmatch(message)
        if candidate is not None:
            confidence = Decimal(candidate["confidence"]) * Decimal("100")
            return (
                f"Candidate {candidate['symbol']} {candidate['side'].upper()} | "
                f"score {confidence:.4f}% | "
                f"{cls._format_candidate_result(candidate['outcome'])}"
            )

        cycle = _CYCLE_EVENT_PATTERN.fullmatch(message)
        if cycle is not None:
            seconds = int(cycle["duration_ms"]) / 1_000
            return (
                f"Discovery complete | scanned {cycle['scanned']} | "
                f"actionable {cycle['actionable']} | "
                f"rank {cycle['rank_start']}-{cycle['rank_end']}/"
                f"{cycle['universe_size']} | {seconds:.2f}s"
            )

        no_entry = _NO_ENTRY_EVENT_PATTERN.fullmatch(message)
        if no_entry is not None:
            return (
                f"No entry {no_entry['symbol']} | "
                f"{cls._format_candidate_result(no_entry['reason'])}"
            )

        preflight = _PREFLIGHT_EVENT_PATTERN.fullmatch(message)
        if preflight is not None:
            return (
                f"Discovery scan | {preflight['interval']} | "
                f"universe {preflight['universe']} | batch {preflight['batch']} | "
                f"top {preflight['top_n']}"
            )

        heartbeat = _HEARTBEAT_EVENT_PATTERN.fullmatch(message)
        if heartbeat is not None:
            strategy = heartbeat["strategy"].replace("_", " ").upper()
            return (
                f"Runtime {heartbeat['state']} | {heartbeat['symbol']} | "
                f"{strategy} | stream {heartbeat['stream']}"
            )

        runner_started = _RUNNER_STARTED_EVENT_PATTERN.fullmatch(message)
        if runner_started is not None:
            context_count = int(runner_started["context_count"])
            context_label = "context" if context_count == 1 else "contexts"
            rendered = (
                f"Runtime started | {runner_started['mode'].upper()} | "
                f"{context_count} {context_label} | "
                f"candle limit {runner_started['candle_limit']}"
            )
            interval_override = runner_started["cycle_interval_override"]
            if interval_override.lower() != "none":
                rendered += f" | cycle {interval_override}s"
            return rendered

        return message.replace("_", " ")

    @staticmethod
    def _format_candidate_result(outcome: str | None) -> str:
        """Present discovery outcomes as short operator-facing labels."""
        labels = {
            "authorization_rejected": "AUTH BLOCK",
            "blocked_by_capacity": "CAPACITY",
            "entry_blocked": "BLOCKED",
            "exchange_rejected": "EXCHANGE REJECT",
            "executed_and_protected": "LIVE",
            "execution_unsafe": "UNSAFE",
            "existing_position": "POSITION EXISTS",
            "market_reference_rejected": "QUOTE REJECT",
            "no_signal": "NO SIGNAL",
            "risk_rejected": "RISK REJECT",
            "skipped_capacity": "CAPACITY",
            "stale_signal": "STALE SIGNAL",
            "submission_blocked": "SUBMISSION BLOCK",
            "symbol_readiness_rejected": "SYMBOL REJECT",
            "venue_rule_rejected": "VENUE REJECT",
        }
        if outcome is None:
            return "PENDING"
        normalized = outcome.strip().lower()
        return labels.get(normalized, normalized.upper().replace("_", " "))

    @staticmethod
    def _compact_status_height(status: TerminalStatus) -> int:
        """Fit compact status to actual safety content instead of fixed whitespace."""
        health = status.live_runtime_health
        if health is None:
            startup_wrap_allowance = 1 if status.missing_startup_requirements else 0
            return 8 + startup_wrap_allowance

        row_count = 8
        if health.reason is not None:
            row_count += 1
        if status.position_count != len(health.contexts):
            row_count += 1
        recovery = status.autonomous_live_recovery
        if recovery is not None:
            row_count += 1
            if recovery.reason is not None:
                row_count += 1
        return row_count + 2

    @staticmethod
    def _compact_discovery_height(status: TerminalStatus) -> int:
        """Collapse unconfigured discovery while preserving telemetry."""
        return 14 if status.global_discovery is not None else 3

    @staticmethod
    def _compact_positions_height(status: TerminalStatus) -> int:
        """Reserve four data rows per compact managed position."""
        context_count = (
            len(status.live_runtime_health.contexts)
            if status.live_runtime_health is not None
            else len(status.positions)
        )
        return 3 if context_count == 0 else context_count * 4 + 2

    def _compact_log_limit(self, status: TerminalStatus) -> int:
        """Reduce log history as managed-position occupancy consumes screen height."""
        context_count = (
            len(status.live_runtime_health.contexts)
            if status.live_runtime_health is not None
            else len(status.positions)
        )
        terminal_height = self.console.size.height
        if context_count >= 4 or terminal_height < 50:
            return 4
        if context_count >= 2 or terminal_height < 60:
            return 6
        return 10
