"""Immutable multi-position runtime context tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from botragram.app import TradingRuntimeControl
from botragram.enums import Interval, StrategyType
from botragram.models import LiveRuntimePortfolioContext, LiveRuntimePositionContext


def _context(
    symbol: str,
    *,
    interval: Interval = Interval.M1,
    strategy_type: StrategyType = StrategyType.EMA_SCALPING,
) -> LiveRuntimePositionContext:
    """Build one validated runtime context."""
    return LiveRuntimePositionContext(
        symbol=symbol,
        interval=interval,
        strategy_type=strategy_type,
    )


def test_runtime_context_normalizes_symbol_and_is_immutable() -> None:
    """Preserve valid domain metadata in an immutable context object."""
    context = _context(" btcusdt ")

    assert context.symbol == "BTCUSDT"
    with pytest.raises(FrozenInstanceError):
        setattr(context, "symbol", "ETHUSDT")


def test_runtime_portfolio_rejects_duplicate_production_identity() -> None:
    """Reject duplicate symbols without deduplicating or changing order."""
    with pytest.raises(ValueError, match="duplicate position symbols"):
        LiveRuntimePortfolioContext(
            contexts=(_context("BTCUSDT"), _context("btcusdt")),
        )


def test_runtime_context_replacement_is_atomic_and_preserves_order() -> None:
    """Keep the previous valid aggregate when a candidate is invalid."""
    control = TradingRuntimeControl()
    sol = _context("SOLUSDT")
    btc = _context("BTCUSDT", interval=Interval.M5)
    eth = _context("ETHUSDT", strategy_type=StrategyType.SUPERTREND)
    control.set_runtime_contexts(contexts=(sol,))
    control.set_runtime_contexts(contexts=(btc, eth))

    assert control.runtime_contexts == (btc, eth)
    with pytest.raises(ValueError, match="duplicate position symbols"):
        control.set_runtime_contexts(contexts=(btc, _context("btcusdt")))
    assert control.runtime_contexts == (btc, eth)


def test_singular_accessors_require_exactly_one_runtime_context() -> None:
    """Reject ambiguous legacy access instead of choosing a primary context."""
    control = TradingRuntimeControl()
    assert control.symbol == "BTCUSDT"
    control.set_runtime_contexts(contexts=(_context("SOLUSDT"),))
    assert control.symbol == "SOLUSDT"
    assert control.interval is Interval.M1
    assert control.strategy_type is StrategyType.EMA_SCALPING

    control.set_runtime_contexts(contexts=(_context("BTCUSDT"), _context("ETHUSDT")))
    with pytest.raises(RuntimeError, match="Singular runtime configuration"):
        _ = control.symbol
    with pytest.raises(RuntimeError, match="Singular runtime configuration"):
        _ = control.interval
    with pytest.raises(RuntimeError, match="Singular runtime configuration"):
        _ = control.strategy_type


def test_clear_contexts_resets_single_and_multiple_runtime_state() -> None:
    """Clear stale contexts and singular stream telemetry idempotently."""
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=(_context("BTCUSDT"), _context("ETHUSDT")))
    control.set_stream_enabled(True)
    control.record_stream_tick(price=Decimal("1"))

    control.clear_runtime_contexts()
    control.clear_runtime_contexts()

    assert control.runtime_contexts == ()
    assert control.symbol == "BTCUSDT"
    assert control.interval is Interval.M15
    assert control.strategy_type is StrategyType.EMA_CROSS
    assert not control.get_stream_telemetry().enabled
    assert control.get_stream_telemetry().event_count == 0
