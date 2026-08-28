"""Responsive terminal dashboard layout regressions."""

from __future__ import annotations

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
from botragram.services.paper_trading_service import PaperPortfolioSnapshot


@dataclass(slots=True, frozen=True)
class _PaperBalanceProvider:
    """Provide an unused deterministic PAPER balance."""

    async def get_portfolio_snapshot(self) -> PaperPortfolioSnapshot:
        return PaperPortfolioSnapshot(
            available_balance=Decimal("100"),
            realized_pnl=Decimal("0"),
        )


@dataclass(slots=True, frozen=True)
class _LiveBalanceProvider:
    """Provide an unused deterministic LIVE balance."""

    async def get_free_balance(self, *, asset: str) -> Decimal:
        assert asset == "USDT"
        return Decimal("100")


@dataclass(slots=True, frozen=True)
class _PositionProvider:
    """Provide an empty portfolio."""

    async def get_open_positions(self) -> tuple[()]:
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


def _render(*, width: int) -> str:
    """Render one dashboard to plain text at a selected width."""
    monitor = _monitor(width=width)
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=width, height=60)
    console.print(monitor.render_dashboard(_status()))
    return output.getvalue()


def test_compact_terminal_prioritizes_mobile_readability() -> None:
    """Stack safety, discovery, positions, and folded logs on portrait widths."""
    rendered = _render(width=72)

    assert "Runtime & Safety" in rendered
    assert "Global Discovery" in rendered
    assert "Managed LIVE Positions" in rendered
    assert "Runtime Events | Log Messages" in rendered
    assert "Trading Performance" not in rendered
    assert "Positions" in rendered
    assert "NONE" in rendered


def test_medium_terminal_uses_two_column_summary() -> None:
    """Keep performance visible once enough horizontal space is available."""
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
