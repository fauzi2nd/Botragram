"""Authoritative LIVE unrealized PnL presentation regressions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

import pytest
from rich.console import Console

from botragram.app import TerminalMonitor, TradingRuntimeControl
from botragram.engine import PnLEngine
from botragram.enums import LiveFuturesUserDataStatus, PositionSide, TradeMode
from botragram.models import FuturesUserDataPositionUpdate, Position
from botragram.services.live_futures_user_data_cache import (
    LiveFuturesUserDataSnapshot,
)
from botragram.services.paper_trading_service import PaperPortfolioSnapshot


@dataclass(slots=True, frozen=True)
class _PaperBalanceProvider:
    async def get_portfolio_snapshot(self) -> PaperPortfolioSnapshot:
        return PaperPortfolioSnapshot(
            available_balance=Decimal("100"),
            realized_pnl=Decimal("0"),
        )


@dataclass(slots=True, frozen=True)
class _LiveBalanceProvider:
    async def get_free_balance(self, *, asset: str) -> Decimal:
        assert asset == "USDT"
        return Decimal("100")


@dataclass(slots=True, frozen=True)
class _PositionProvider:
    position: Position

    async def get_open_positions(self) -> Sequence[Position]:
        return (self.position,)


@dataclass(slots=True, frozen=True)
class _UserDataProvider:
    snapshot: LiveFuturesUserDataSnapshot

    async def get_snapshot(self) -> LiveFuturesUserDataSnapshot:
        return self.snapshot


def _position() -> Position:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("101"),
        unrealized_pnl=Decimal("1"),
        leverage=20,
        opened_at=observed_at,
        updated_at=observed_at,
    )


def _snapshot(*, status: LiveFuturesUserDataStatus) -> LiveFuturesUserDataSnapshot:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    return LiveFuturesUserDataSnapshot(
        status=status,
        last_event_at=observed_at,
        last_snapshot_at=observed_at,
        balances=(),
        positions=(),
        position_updates=(
            FuturesUserDataPositionUpdate(
                symbol="BTCUSDT",
                quantity=Decimal("1"),
                entry_price=Decimal("100"),
                unrealized_pnl=Decimal("7.25"),
            ),
        ),
        recent_orders=(),
    )


def _monitor(*, user_data: LiveFuturesUserDataSnapshot) -> TerminalMonitor:
    monitor = TerminalMonitor(
        runtime_control=TradingRuntimeControl(symbol="BTCUSDT"),
        paper_balance_provider=_PaperBalanceProvider(),
        live_balance_provider=_LiveBalanceProvider(),
        position_provider=_PositionProvider(position=_position()),
        pnl_engine=PnLEngine(),
        trade_mode=TradeMode.LIVE,
        quote_asset="USDT",
        console=Console(file=StringIO(), force_terminal=False, width=72, height=60),
    )
    monitor.live_futures_user_data_service = _UserDataProvider(snapshot=user_data)
    return monitor


@pytest.mark.asyncio
async def test_ready_private_futures_state_drives_total_unrealized_pnl() -> None:
    """Use the same Binance private PnL source as per-position presentation."""
    monitor = _monitor(user_data=_snapshot(status=LiveFuturesUserDataStatus.READY))

    status = await monitor.collect_status()

    assert status.positions[0].unrealized_pnl == Decimal("7.25")
    assert status.unrealized_pnl == Decimal("7.25")


@pytest.mark.asyncio
async def test_nonready_private_futures_state_keeps_existing_pnl_fallback() -> None:
    """Do not trust cached private PnL while Futures state is resynchronizing."""
    monitor = _monitor(
        user_data=_snapshot(status=LiveFuturesUserDataStatus.RESYNCING),
    )

    status = await monitor.collect_status()

    assert status.positions[0].unrealized_pnl == Decimal("1")
    assert status.unrealized_pnl == Decimal("1")


@pytest.mark.asyncio
async def test_active_market_stream_drives_realtime_position_and_total_pnl() -> None:
    """Prefer real-time market stream calculation over static private snapshot."""
    monitor = _monitor(user_data=_snapshot(status=LiveFuturesUserDataStatus.READY))
    monitor.runtime_control.set_stream_enabled(True)
    monitor.runtime_control.record_stream_tick(price=Decimal("115"))

    status = await monitor.collect_status()

    # (115 - 100) * 1 = 15 instead of the stale 7.25
    assert status.positions[0].current_price == Decimal("115")
    assert status.positions[0].unrealized_pnl == Decimal("15")
    assert status.unrealized_pnl == Decimal("15")
