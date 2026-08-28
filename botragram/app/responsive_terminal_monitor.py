"""
Botragram

Description:
    Width-aware Rich terminal dashboard presentation.

Python:
    3.14+
"""

from __future__ import annotations

from typing import Final

from rich import box
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from botragram.app.terminal_monitor import TerminalMonitor as BaseTerminalMonitor
from botragram.app.terminal_monitor import TerminalStatus

__all__ = ["TerminalMonitor"]

_COMPACT_WIDTH: Final[int] = 90
_MEDIUM_WIDTH: Final[int] = 140


class TerminalMonitor(BaseTerminalMonitor):
    """Render the existing monitor data with width-aware Rich layouts."""

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
        """Prioritize operational safety and logs on narrow portrait terminals."""
        managed_height = self._compact_positions_height(status)
        discovery_height = 14 if status.global_discovery is not None else 5
        layout = Layout(name="root")
        layout.split_column(
            Layout(
                self._build_status_panel(status),
                name="status",
                size=15,
            ),
            Layout(
                self._build_discovery_panel(status),
                name="discovery",
                size=discovery_height,
            ),
            Layout(
                self._build_compact_positions_panel(status),
                name="managed_positions",
                size=managed_height,
            ),
            Layout(
                self._build_compact_log_panel(),
                name="logs",
                minimum_size=8,
            ),
        )
        return layout

    def _build_compact_positions_panel(self, status: TerminalStatus) -> Panel:
        """Render managed positions as vertical key/value blocks on small screens."""
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="bright_magenta", no_wrap=True)
        table.add_column(style="white")
        health_snapshot = status.live_runtime_health

        if health_snapshot is None:
            if not status.positions:
                table.add_row("Positions", "NONE")
            else:
                for position in status.positions:
                    self._add_compact_position_rows(
                        table=table,
                        symbol=position.symbol,
                        side=position.side.value.upper(),
                        leverage=position.leverage,
                        quantity=self._format_compact_decimal(position.quantity),
                        entry=self._format_compact_decimal(position.entry_price),
                        mark=self._format_compact_decimal(position.current_price),
                        pnl=self.format_position_pnl(position.unrealized_pnl),
                        stop_loss=self._format_compact_price(position.stop_loss),
                        take_profit=self._format_compact_price(position.take_profit),
                        step=position.protection_step,
                        health="PAPER",
                    )
        elif not health_snapshot.contexts:
            table.add_row("Positions", "NONE")
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
                if position is None:
                    table.add_row(context.symbol, "POSITION MISSING")
                    continue
                mark = (
                    self._get_matching_stream_price(
                        position=position,
                        stream_states=health_snapshot.stream_states,
                    )
                    or position.current_price
                )
                self._add_compact_position_rows(
                    table=table,
                    symbol=context.symbol,
                    side=position.side.value.upper(),
                    leverage=position.leverage,
                    quantity=self._format_compact_decimal(position.quantity),
                    entry=self._format_compact_decimal(position.entry_price),
                    mark=self._format_compact_decimal(mark),
                    pnl=self.format_position_pnl(position.unrealized_pnl),
                    stop_loss=self._format_compact_price(position.stop_loss),
                    take_profit=self._format_compact_price(position.take_profit),
                    step=position.protection_step,
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
        """Append one mobile-readable managed-position block."""
        table.add_row(symbol, f"{side} | {leverage}x | {health}")
        table.add_row("Qty / PnL", f"{quantity} / {pnl}")
        table.add_row("Entry / Mark", f"{entry} / {mark}")
        table.add_row("SL / TP", f"{stop_loss} / {take_profit}")
        table.add_row("Protection Step", str(step))

    def _build_compact_log_panel(self) -> Panel:
        """Use a two-column folded log table on narrow terminals."""
        table = Table(
            box=box.SIMPLE_HEAD,
            expand=True,
            show_edge=False,
            pad_edge=False,
        )
        table.add_column("Time", width=12, no_wrap=True, style="bright_cyan")
        table.add_column("Event", ratio=1, overflow="fold")
        entries = self.log_handler.get_entries()[-10:]

        if not entries:
            table.add_row("-", "INFO dashboard | Waiting for application logs...")
        else:
            for entry in entries:
                level = Text(
                    entry.level_name,
                    style=self._get_log_level_style(entry.level_name),
                )
                details = Text.assemble(
                    level,
                    " ",
                    entry.logger_name.removeprefix("botragram."),
                    " | ",
                    entry.message,
                )
                table.add_row(
                    entry.observed_at.strftime("%H:%M:%S.%f")[:-3],
                    details,
                )

        return Panel(
            table,
            title="[bold]Runtime Events | Log Messages[/bold]",
            border_style="blue",
        )

    @staticmethod
    def _compact_positions_height(status: TerminalStatus) -> int:
        """Reserve vertical rows for mobile position blocks without wide columns."""
        context_count = (
            len(status.live_runtime_health.contexts)
            if status.live_runtime_health is not None
            else len(status.positions)
        )
        return max(5, context_count * 5 + 3)
