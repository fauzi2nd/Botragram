"""Regression tests for sequential context cadence scheduling."""

from __future__ import annotations

from botragram.app.context_cycle_scheduler import ContextCycleScheduler
from botragram.enums import Interval, StrategyType
from botragram.models import LiveRuntimePositionContext

__all__: list[str] = []


def _context(symbol: str, interval: Interval) -> LiveRuntimePositionContext:
    """Create an immutable context with a stable strategy identity."""
    return LiveRuntimePositionContext(
        symbol=symbol,
        interval=interval,
        strategy_type=StrategyType.EMA_CROSS,
    )


def test_scheduler_preserves_order_and_per_context_cadence() -> None:
    """Only due contexts run, and each completed context gets its own deadline."""
    first = _context("BTCUSDT", Interval.M1)
    second = _context("ETHUSDT", Interval.M5)
    scheduler = ContextCycleScheduler()

    assert scheduler.eligible(contexts=(first, second), now=100.0) == (first, second)
    scheduler.mark_completed(
        contexts=(first, second),
        completed_at=100.0,
        cycle_interval_seconds=None,
    )

    assert scheduler.eligible(contexts=(first, second), now=160.0) == (first,)
    assert scheduler.next_deadline(contexts=(first, second), now=160.0) == 160.0
    scheduler.prune(contexts=(second,))
    assert scheduler.eligible(contexts=(first, second), now=100.0) == (first,)


def test_scheduler_override_and_empty_batch() -> None:
    """An explicit interval overrides candle cadence; empty batches are due now."""
    context = _context("BTCUSDT", Interval.M1)
    scheduler = ContextCycleScheduler()
    scheduler.mark_completed(
        contexts=(context,),
        completed_at=10.0,
        cycle_interval_seconds=5.0,
    )

    assert scheduler.eligible(contexts=(context,), now=14.0) == ()
    assert scheduler.next_deadline(contexts=(context,), now=14.0) == 15.0
    assert scheduler.next_deadline(contexts=(), now=14.0) == 14.0
