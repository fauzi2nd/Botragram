"""Regression coverage for terminal telemetry during exchange outages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from io import StringIO
from socket import gaierror

import pytest

from botragram.app import TerminalMonitor, TradingRuntimeControl
from botragram.engine import PnLEngine
from botragram.enums import TradeMode
from tests.terminal_helpers import create_terminal_console
from tests.test_terminal_monitor import FakePaperBalanceProvider, FakePositionProvider

__all__: list[str] = []


@dataclass(slots=True)
class BalanceProvider:
    """Provide a controllable exchange boundary for outage and recovery tests."""

    error: BaseException | None = None
    calls: int = 0

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return a balance or raise the configured boundary failure."""
        self.calls += 1
        if self.error is not None:
            raise self.error
        return Decimal("500")


def create_monitor() -> TerminalMonitor:
    """Compose a network-free LIVE monitor using existing test boundaries."""
    return TerminalMonitor(
        runtime_control=TradingRuntimeControl(),
        paper_balance_provider=FakePaperBalanceProvider(balance=Decimal("10000")),
        live_balance_provider=BalanceProvider(),
        position_provider=FakePositionProvider(),
        pnl_engine=PnLEngine(),
        trade_mode=TradeMode.LIVE,
        quote_asset="USDT",
        console=create_terminal_console(file=StringIO(), width=170, height=50),
    )


@pytest.mark.parametrize("cached", [False, True])
def test_outage_keeps_dashboard_available_and_recovers(
    cached: bool, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Render unknown or stale balance without polling every dashboard frame."""
    clock = [100.0]
    monkeypatch.setattr(
        "botragram.app.terminal.terminal_monitor.monotonic", lambda: clock[0]
    )
    monitor = create_monitor()
    provider = BalanceProvider()
    monitor.live_balance_provider = provider
    if cached:
        asyncio.run(monitor.collect_status())
        clock[0] += 11
    provider.error = gaierror(11001, "DNS unavailable")
    status = asyncio.run(monitor.collect_status())
    assert not status.balance_is_fresh
    assert status.balance_is_available is cached
    line = asyncio.run(monitor.refresh())
    label = "STALE" if cached else "UNAVAILABLE"
    assert label in line
    output = StringIO()
    create_terminal_console(file=output, width=170, height=50).print(
        monitor.render_dashboard(status)
    )
    assert label in output.getvalue()
    assert provider.calls == (2 if cached else 1)
    assert all(record.exc_info is None for record in caplog.records)
    clock[0] += 31
    provider.error = None
    recovered = asyncio.run(monitor.collect_status())
    assert recovered.balance == Decimal("500")
    assert recovered.balance_is_fresh
    assert recovered.balance_is_available
    assert provider.calls == (3 if cached else 2)


@pytest.mark.parametrize(
    "error", [ValueError("invalid balance"), asyncio.CancelledError()]
)
def test_terminal_does_not_hide_domain_errors_or_cancellation(
    error: BaseException,
) -> None:
    """Propagate failures that must not become cached outage telemetry."""
    monitor = create_monitor()
    monitor.live_balance_provider = BalanceProvider(error=error)
    with pytest.raises(type(error)):
        asyncio.run(monitor.collect_status())


class HangingBalanceProvider:
    """Simulate a request that never completes before the monitor deadline."""

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Wait until cancelled by the terminal timeout."""
        await asyncio.Event().wait()
        raise AssertionError("Unreachable")


def test_terminal_bounds_hanging_balance_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled exchange request must not indefinitely freeze the dashboard."""
    monkeypatch.setattr(
        "botragram.app.terminal.terminal_monitor._LIVE_BALANCE_TIMEOUT_SECONDS", 0.01
    )
    monitor = create_monitor()
    monitor.live_balance_provider = HangingBalanceProvider()

    async def collect() -> None:
        async with asyncio.timeout(1):
            status = await monitor.collect_status()
        assert not status.balance_is_available
        assert not status.balance_is_fresh

    asyncio.run(collect())
