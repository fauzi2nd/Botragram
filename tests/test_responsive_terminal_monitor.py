"""Responsive terminal dashboard layout regressions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

from rich.console import Console

from botragram.app import TerminalMonitor, TradingRuntimeControl
from botragram.app.runtime_control import MarketStreamTelemetry
from botragram.app.terminal_monitor import TerminalStatus
from botragram.engine import PnLEngine
from botragram.enums import PositionSide, TradeMode
from botragram.models import Position
from botragram.services.paper_trading_service import PaperPortfolioSnapshot


@dataclass(slots=True, frozen=True)
class _PaperBalanceProvider:
    """Provide an unused deterministic PAPER balance."""

    async def get_portfolio_snapshot(self) -> PaperPortfolioSnapshot:
        """Return a deterministic PAPER balance snapshot."""
        return PaperPortfolioSnapshot(
            available_balance=Decimal("100"),
            realized_pnl=Decimal("0"),
        )


@dataclass(slots=True, frozen=True)
class _LiveBalanceProvider:
    """Provide an unused deterministic LIVE balance."""

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return a deterministic LIVE free balance snapshot."""
        assert asset == "USDT"
        return Decimal("100")


@dataclass(slots=True, frozen=True)
class _PositionProvider:
    """Provide an empty portfolio."""

    async def get_open_positions(self) -> tuple[Position, ...]:
        """Return no open positions."""
        return ()


def _monitor(*, width: int, height: int = 60) -> TerminalMonitor:
    """Build one monitor against deterministic terminal dimensions."""
    return TerminalMonitor(
        runtime_control=TradingRuntimeControl(),
        paper_balance_provider=_PaperBalanceProvider(),
        live_balance_provider=_LiveBalanceProvider(),
        position_provider=_PositionProvider(),
        pnl_engine=PnLEngine(),
        trade_mode=TradeMode.LIVE,
        quote_asset="USDT",
        console=Console(
            file=StringIO(),
            force_terminal=False,
            width=width,
            height=height,
        ),
    )


def _status(*, positions: tuple[Position, ...] = ()) -> TerminalStatus:
    """Build one terminal snapshot with optional managed-position data."""
    return TerminalStatus(
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        balance=Decimal("100"),
        position_count=len(positions),
        unrealized_pnl=sum(
            (position.unrealized_pnl for position in positions),
            start=Decimal("0"),
        ),
        stream=MarketStreamTelemetry(
            enabled=False,
            event_count=0,
            last_price=None,
            last_event_monotonic=None,
        ),
        stream_rate=0.0,
        stream_age_ms=None,
        missing_startup_requirements=(),
        positions=positions,
    )


def _position(index: int, *, leverage: int = 1) -> Position:
    """Build one deterministic protected position for portrait rendering."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Position(
        symbol=f"PAIR{index}USDT",
        side=PositionSide.LONG if index % 2 else PositionSide.SHORT,
        quantity=Decimal("1.25"),
        entry_price=Decimal("100"),
        current_price=Decimal("101"),
        unrealized_pnl=Decimal("1.25"),
        leverage=leverage,
        opened_at=now,
        updated_at=now,
        stop_loss=Decimal("98"),
        take_profit=Decimal("104"),
        protection_step=index,
    )


def _render(
    *,
    width: int,
    monitor: TerminalMonitor | None = None,
    status: TerminalStatus | None = None,
) -> str:
    """Render one dashboard to plain text at selected terminal dimensions."""
    active_monitor = monitor or _monitor(width=width)
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        width=width,
        height=active_monitor.console.size.height,
    )
    console.print(active_monitor.render_dashboard(status or _status()))
    return output.getvalue()


def test_compact_terminal_keeps_readable_performance_summary() -> None:
    """Stack safety, discovery, performance, positions, and logs on portrait widths."""
    rendered = _render(width=72)

    assert "Runtime & Safety" in rendered
    assert "Strategy Type" not in rendered
    assert "Global Discovery" in rendered
    assert "Trading Performance" in rendered
    assert "Trades / W-L" in rendered
    assert "Win Rate / PnL" in rendered
    assert "Managed LIVE Positions" in rendered
    assert "Runtime Events" in rendered
    assert "Positions" in rendered
    assert "NONE" in rendered


def test_compact_terminal_collapses_minimal_panels_to_content() -> None:
    """Give unused portrait height back to runtime events during startup."""
    monitor = _monitor(width=72, height=60)
    layout = monitor.render_dashboard(_status())

    assert layout["status"].size == 8
    assert layout["discovery"].size == 3
    assert layout["performance"].size == 4
    assert layout["managed_positions"].size == 3
    assert layout["logs"].minimum_size == 8


def test_compact_terminal_humanizes_discovery_rejection_events() -> None:
    """Hide internal snake-case diagnostics from the portrait operator view."""
    monitor = _monitor(width=72)
    record = logging.LogRecord(
        name="botragram.app.trading_runner",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=(
            "Global discovery candidate processed: symbol=MAGICUSDT side=sell "
            "confidence=0.0002516 outcome=market_reference_rejected"
        ),
        args=(),
        exc_info=None,
    )
    monitor.log_handler.emit(record)

    rendered = _render(width=72, monitor=monitor)

    assert "Candidate MAGICUSDT SELL" in rendered
    assert "QUOTE REJECT" in rendered
    assert "market_reference_rejected" not in rendered
    assert "trading_runner" not in rendered


def test_compact_terminal_humanizes_runner_start_event() -> None:
    """Present startup telemetry without raw snake-case key/value syntax."""
    monitor = _monitor(width=72)
    record = logging.LogRecord(
        name="botragram.app.trading_runner",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=(
            "Trading runner started: context_count=1 mode=paper candle_limit=100 "
            "cycle_interval_override=None"
        ),
        args=(),
        exc_info=None,
    )
    monitor.log_handler.emit(record)

    rendered = _render(width=72, monitor=monitor)

    assert "Runtime started" in rendered
    assert "PAPER" in rendered
    assert "1 context" in rendered
    assert "context_count" not in rendered
    assert "cycle_interval_override" not in rendered
    assert "trading_runner" not in rendered


def test_compact_terminal_keeps_five_positions_with_readable_price_rows() -> None:
    """Fit five position summaries while keeping each price pair independently readable."""
    positions = tuple(_position(index) for index in range(1, 6))
    monitor = _monitor(width=72, height=60)

    rendered = _render(
        width=72,
        monitor=monitor,
        status=_status(positions=positions),
    )

    for index in range(1, 6):
        assert f"PAIR{index}USDT" in rendered
        assert f"STEP {index}" in rendered
    assert "Entry / Mark" in rendered
    assert "SL / TP" in rendered
    assert "100 / 101" in rendered
    assert "98 / 104" in rendered
    assert "Entry / Mark / SL / TP" not in rendered
    assert "Protection Step" not in rendered
    assert "Strategy Type" not in rendered
    assert "Runtime Events" in rendered


def test_compact_terminal_marks_nonpositive_leverage_unavailable() -> None:
    """Do not present an unknown or invalid leverage value as zero leverage."""
    rendered = _render(
        width=72,
        status=_status(positions=(_position(1, leverage=0),)),
    )

    assert "PAIR1USDT" in rendered
    assert "LONG | N/A | PAPER | STEP 1" in rendered
    assert "0x" not in rendered


def test_medium_terminal_uses_two_column_summary() -> None:
    """Keep full performance visible once enough horizontal space is available."""
    rendered = _render(width=110)

    assert "Runtime & Safety" in rendered
    assert "Trading Performance" in rendered
    assert "Global Discovery" in rendered
    assert "Managed LIVE Positions" in rendered


def test_wide_terminal_keeps_existing_desktop_dashboard() -> None:
    """Preserve the established three-column desktop presentation."""
    rendered = _render(width=160)

    assert "Runtime & Safety" in rendered
    assert "Trading Performance" in rendered
    assert "Global Discovery" in rendered
    assert "Managed LIVE Positions" in rendered
