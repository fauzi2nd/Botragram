"""Immutable multi-position runtime context tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from botragram.app import TradingRuntimeControl
from botragram.enums import Interval, StrategyType
from botragram.models import (
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePortfolioContext,
    LiveRuntimePositionContext,
)


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


def test_clear_contexts_preserves_configured_future_cycle_defaults() -> None:
    """Restore deployment configuration after managed contexts disappear."""
    control = TradingRuntimeControl(
        symbol="ETHUSDT",
        interval=Interval.M5,
        strategy_type=StrategyType.SUPERTREND,
    )
    control.set_runtime_contexts(contexts=(_context("BTCUSDT"), _context("SOLUSDT")))
    control.clear_runtime_contexts()

    assert control.runtime_contexts == ()
    assert control.symbol == "ETHUSDT"
    assert control.interval is Interval.M5
    assert control.strategy_type is StrategyType.SUPERTREND


def test_single_managed_live_context_resumes_without_legacy_configuration() -> None:
    """Activate one exact managed LIVE context without Telegram confirmations."""
    control = TradingRuntimeControl()
    contexts = (_context("BTCUSDT"),)
    control.set_runtime_contexts(contexts=contexts)
    control.set_position_protection_ready(False)
    control.set_position_protection_ready(True)
    control.set_live_management_authorization(
        authorization=LiveRecoveredPositionManagementAuthorization(
            contexts=contexts,
            runtime_management_allowed=True,
        )
    )

    assert control.get_missing_configuration_requirements() == (
        "exchange",
        "market type",
        "symbol",
        "interval",
        "strategy",
    )
    assert control.resume()
    assert not control.is_paused


def test_single_managed_live_context_requires_ready_protection() -> None:
    """Reject authorized managed LIVE activation while protection is closed."""
    control = TradingRuntimeControl()
    contexts = (_context("BTCUSDT"),)
    control.set_runtime_contexts(contexts=contexts)
    control.set_live_management_authorization(
        authorization=LiveRecoveredPositionManagementAuthorization(
            contexts=contexts,
            runtime_management_allowed=True,
        )
    )
    control.set_position_protection_ready(False)

    with pytest.raises(RuntimeError, match="verified position protection"):
        control.resume()
    assert control.is_paused


def test_single_context_without_live_authorization_keeps_legacy_requirements() -> None:
    """Preserve manual and PAPER startup gates without LIVE authorization."""
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=(_context("BTCUSDT"),))

    assert control.get_missing_startup_requirements() == (
        "exchange",
        "market type",
        "symbol",
        "interval",
        "strategy",
        "stream subscription",
    )
    with pytest.raises(RuntimeError, match="Startup configuration incomplete"):
        control.resume()
    assert control.is_paused
