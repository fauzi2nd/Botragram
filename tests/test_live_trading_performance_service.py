"""
Botragram

Description:
    LIVE realized-fill performance aggregation tests.

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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OrderSide
from botragram.models import Trade
from botragram.services.live_trading_performance_service import (
    LiveTradingPerformanceService,
)


# =============================================================================
# Test Fakes
# =============================================================================
@dataclass(slots=True, kw_only=True)
class FakeLiveTradeHistory:
    """Return deterministic account fills while recording bounded reads."""

    trades: tuple[Trade, ...]
    calls: int = 0

    async def get_trades(
        self,
        *,
        symbol: str | None,
        limit: int,
    ) -> Sequence[Trade]:
        """Return the configured account-wide Futures fills."""
        assert symbol is None
        assert limit == 1_000
        self.calls += 1
        return self.trades


@dataclass(slots=True)
class MutableClock:
    """Provide deterministic monotonic time for refresh-cache testing."""

    value: float = 0.0

    def __call__(self) -> float:
        """Return the current deterministic monotonic value."""
        return self.value


def _trade(*, trade_id: str, order_id: str, realized_pnl: str | None) -> Trade:
    """Create one Futures fill with an optional authoritative realized PnL."""
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        price=Decimal("100"),
        quantity=Decimal("1"),
        quote_quantity=Decimal("100"),
        fee=Decimal("0.01"),
        fee_asset="USDT",
        executed_at=datetime(2026, 8, 25, tzinfo=UTC),
        realized_pnl=(Decimal(realized_pnl) if realized_pnl is not None else None),
    )


# =============================================================================
# Aggregation Tests
# =============================================================================
def test_live_performance_aggregates_authoritative_order_outcomes() -> None:
    """Count each closing order once while summing its partial fill profit."""
    asyncio.run(_run_live_performance_aggregation_test())


async def _run_live_performance_aggregation_test() -> None:
    """Aggregate wins, losses, break-even outcomes, and realized PnL."""
    history = FakeLiveTradeHistory(
        trades=(
            _trade(trade_id="1", order_id="win", realized_pnl="2"),
            _trade(trade_id="2", order_id="win", realized_pnl="3"),
            _trade(trade_id="3", order_id="loss", realized_pnl="-2"),
            _trade(trade_id="4", order_id="flat", realized_pnl="0"),
            _trade(trade_id="5", order_id="spot", realized_pnl=None),
        )
    )
    service = LiveTradingPerformanceService(exchange_client=history)

    snapshot = await service.get_snapshot()

    assert history.calls == 1
    assert snapshot.closed_trade_count == 3
    assert snapshot.win_count == 1
    assert snapshot.loss_count == 1
    assert snapshot.break_even_count == 1
    assert snapshot.realized_pnl == Decimal("3")
    assert snapshot.win_rate_percent == Decimal("100") / Decimal("3")


def test_live_performance_caches_account_history_within_refresh_window() -> None:
    """Avoid repeated authenticated fills polling during terminal refreshes."""
    asyncio.run(_run_live_performance_cache_test())


async def _run_live_performance_cache_test() -> None:
    """Reuse one immutable snapshot until the configured cache expires."""
    clock = MutableClock()
    history = FakeLiveTradeHistory(
        trades=(_trade(trade_id="1", order_id="win", realized_pnl="1"),)
    )
    service = LiveTradingPerformanceService(
        exchange_client=history,
        refresh_seconds=10.0,
        monotonic_clock=clock,
    )

    first = await service.get_snapshot()
    clock.value = 9.9
    second = await service.get_snapshot()
    clock.value = 10.0
    third = await service.get_snapshot()

    assert first is second
    assert third == first
    assert history.calls == 2


@pytest.mark.parametrize(
    ("refresh_seconds", "trade_history_limit", "message"),
    ((0.0, 1_000, "refresh interval"), (10.0, 0, "trade-history limit")),
)
def test_live_performance_rejects_invalid_history_configuration(
    refresh_seconds: float,
    trade_history_limit: int,
    message: str,
) -> None:
    """Reject non-positive bounded-polling configuration values."""
    with pytest.raises(ValueError, match=message):
        LiveTradingPerformanceService(
            exchange_client=FakeLiveTradeHistory(trades=()),
            refresh_seconds=refresh_seconds,
            trade_history_limit=trade_history_limit,
        )
