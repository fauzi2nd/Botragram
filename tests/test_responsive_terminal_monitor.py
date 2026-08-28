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
from botragram.enums import TradeMode
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
        """Return a deterministic LIVE free balance."""
        assert asset == "USDT"
        return Decimal("100")


@dataclass(slots=True, frozen=True)
class _PositionProvider:
    """Provide an empty portfolio."""

    async def get_open_positions(self) -> tuple[Position, ...]:
        """Return no open positions."""
        return ()


def _monitor(*, width: int) -> TerminalMonitor:
    """Build one monitor against a deterministic terminal width."""
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
            height=60,
        ),
    )


def _status() -> TerminalStatus:
    """Build one minimal terminal snapshot with no managed positions."""
    return TerminalStatus(
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        balance=Decimal("100"),
        position_count=0,
        unrealized_pnl=Decimal("0"),
        stream=MarketStreamTelemetry(
            enabled=False,
            event_count=0,
            last_price=None,
            last_event_monotonic=None,
        ),
        stream_rate=0.0,
        stream_age_ms=None,
        missing_startup_requirements=(),
    )


def _render(*, width: int, monitor: TerminalMonitor | None = None) -> str:
    """Render one dashboard to plain text at a selected width."""
    active_monitor = monitor or _monitor(width=width)
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=width, height=60)
    console.print(active_monitor.render_dashboard(_status()))
    return output.getvalue()


def test_compact_terminal_keeps_readable_performance_summary() -> None:
    """Stack safety, discovery, performance, positions, and logs on portrait widths."""
    rendered = _render(width=72)

    assert "Runtime & Safety" in rendered
    assert "Global Discovery" in rendered
    assert "Trading Performance" in rendered
    assert "Trades / W-L" in rendered
    assert "Win Rate / PnL" in rendered
    assert "Managed LIVE Positions" in rendered
    assert "Runtime Events" in rendered
    assert "Positions" in rendered
    assert "NONE" in rendered


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
