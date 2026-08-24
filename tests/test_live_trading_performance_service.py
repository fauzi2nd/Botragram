"""LIVE Botragram-only realized performance aggregation tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.enums import OrderSide
from botragram.models import Trade
from botragram.services.live_trading_performance_service import (
    LiveTradingPerformanceService,
)
from botragram.storage import MemoryTradeRepository


@dataclass(slots=True)
class MutableClock:
    """Provide deterministic monotonic time for refresh-cache testing."""

    value: float = 0.0

    def __call__(self) -> float:
        """Return the current deterministic monotonic value."""
        return self.value


def _trade(*, trade_id: str, order_id: str, realized_pnl: str | None) -> Trade:
    """Create one fill with an optional authoritative realized PnL."""
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


def test_live_performance_aggregates_only_persisted_live_bot_outcomes() -> None:
    """Exclude PAPER rows while counting each Botragram closing order once."""
    asyncio.run(_run_live_performance_aggregation_test())


async def _run_live_performance_aggregation_test() -> None:
    """Aggregate wins, losses, break-even outcomes, and realized PnL."""
    repository = MemoryTradeRepository()
    await repository.save_many(
        trades=(
            _trade(trade_id="1", order_id="win", realized_pnl="2"),
            _trade(trade_id="2", order_id="win", realized_pnl="3"),
            _trade(trade_id="3", order_id="loss", realized_pnl="-2"),
            _trade(trade_id="4", order_id="flat", realized_pnl="0"),
            _trade(trade_id="5", order_id="paper-manual", realized_pnl="99"),
            _trade(trade_id="6", order_id="spot", realized_pnl=None),
        )
    )
    service = LiveTradingPerformanceService(trade_repository=repository)

    snapshot = await service.get_snapshot()

    assert snapshot.closed_trade_count == 3
    assert snapshot.win_count == 1
    assert snapshot.loss_count == 1
    assert snapshot.break_even_count == 1
    assert snapshot.realized_pnl == Decimal("3")
    assert snapshot.win_rate_percent == Decimal("50")


def test_live_performance_caches_local_ledger_within_refresh_window() -> None:
    """Avoid repeated dashboard aggregation before the local cache expires."""
    asyncio.run(_run_live_performance_cache_test())


async def _run_live_performance_cache_test() -> None:
    """Reuse one immutable snapshot until the configured cache expires."""
    clock = MutableClock()
    repository = MemoryTradeRepository()
    await repository.save(trade=_trade(trade_id="1", order_id="win", realized_pnl="1"))
    service = LiveTradingPerformanceService(
        trade_repository=repository,
        refresh_seconds=10.0,
        monotonic_clock=clock,
    )

    first = await service.get_snapshot()
    await repository.save(
        trade=_trade(trade_id="2", order_id="loss", realized_pnl="-1")
    )
    clock.value = 9.9
    second = await service.get_snapshot()
    clock.value = 10.0
    third = await service.get_snapshot()

    assert first is second
    assert third.closed_trade_count == 2
    assert third.realized_pnl == Decimal("0")


@pytest.mark.parametrize(
    ("refresh_seconds", "trade_history_limit", "message"),
    ((0.0, 1_000, "refresh interval"), (10.0, 0, "trade-history limit")),
)
def test_live_performance_rejects_invalid_history_configuration(
    refresh_seconds: float,
    trade_history_limit: int,
    message: str,
) -> None:
    """Reject non-positive bounded local-ledger configuration values."""
    with pytest.raises(ValueError, match=message):
        LiveTradingPerformanceService(
            trade_repository=MemoryTradeRepository(),
            refresh_seconds=refresh_seconds,
            trade_history_limit=trade_history_limit,
        )
