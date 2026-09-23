"""
Botragram

Description:
    Regression tests for SignalEngine filter state detection and evaluation invariants.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine.signal_engine import (
    SignalEngine,
    has_account_ratio_evaluation,
    has_funding_evaluation,
    has_oi_evaluation,
)
from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy
from botragram.strategies.factory import StrategyResolver


# =============================================================================
# Test Mocks
# =============================================================================
class MockStrategy(BaseStrategy):
    """Mock strategy with spy counters for filter execution."""

    def __init__(self, initial_signal: Signal) -> None:
        super().__init__()
        self.initial_signal = initial_signal
        self.oi_calls = 0
        self.funding_calls = 0
        self.account_ratio_calls = 0

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.BOTRAGRAM_ORIGIN

    @property
    def minimum_candles(self) -> int:
        return 5

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        del candles
        return self.initial_signal

    def apply_open_interest_confluence(
        self,
        *,
        signal: Signal,
        candles: Sequence[Candle],
        min_change_pct: Decimal = Decimal("0.0"),
        confidence_bonus: Decimal = Decimal("0.05"),
        strict: bool = False,
    ) -> Signal:
        del candles, min_change_pct, confidence_bonus, strict
        self.oi_calls += 1
        return Signal(
            symbol=signal.symbol,
            signal_type=signal.signal_type,
            price=signal.price,
            confidence=signal.confidence,
            strategy_name=signal.strategy_name,
            generated_at=signal.generated_at,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=f"{signal.reason} [Bullish Long Buildup: Δ1=+2.5%]",
        )

    def apply_funding_sentiment_filter(
        self,
        *,
        signal: Signal,
        candles: Sequence[Candle],
        max_long_funding: Decimal = Decimal("0.0005"),
        min_short_funding: Decimal = Decimal("-0.0005"),
        strict: bool = True,
    ) -> Signal:
        del candles, max_long_funding, min_short_funding, strict
        self.funding_calls += 1
        return Signal(
            symbol=signal.symbol,
            signal_type=signal.signal_type,
            price=signal.price,
            confidence=signal.confidence,
            strategy_name=signal.strategy_name,
            generated_at=signal.generated_at,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=f"{signal.reason} [CROWDED_LONG: funding 0.0800%]",
        )

    def apply_account_ratio_filter(
        self,
        *,
        signal: Signal,
        candles: Sequence[Candle],
        max_long_ratio: Decimal = Decimal("0.75"),
        min_short_ratio: Decimal = Decimal("0.25"),
        strict: bool = True,
        confirm_htf: bool = False,
    ) -> Signal:
        del candles, max_long_ratio, min_short_ratio, strict, confirm_htf
        self.account_ratio_calls += 1
        return Signal(
            symbol=signal.symbol,
            signal_type=signal.signal_type,
            price=signal.price,
            confidence=signal.confidence,
            strategy_name=signal.strategy_name,
            generated_at=signal.generated_at,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=f"{signal.reason} [Top Trader L/S 2.80 > max 2.50 (crowded long)]",
        )


class MockResolver(StrategyResolver):
    """Test resolver returning the given MockStrategy."""

    def __init__(self, strategy: MockStrategy) -> None:
        super().__init__(strategies={StrategyType.BOTRAGRAM_ORIGIN: strategy})
        self.strategy = strategy

    def resolve(self, *, strategy_type: StrategyType) -> BaseStrategy:
        del strategy_type
        return self.strategy


def _dummy_candle() -> Candle:
    now = datetime.now(timezone.utc)
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M5,
        open_time=now,
        close_time=now,
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("95"),
        close_price=Decimal("100"),
        volume=Decimal("1000"),
    )


def _dummy_signal(
    *, reason: str = "Base pattern", signal_type: SignalType = SignalType.BUY
) -> Signal:
    return Signal(
        symbol="BTCUSDT",
        signal_type=signal_type,
        price=Decimal("100"),
        confidence=Decimal("0.80"),
        strategy_name=StrategyType.BOTRAGRAM_ORIGIN.value,
        generated_at=datetime.now(timezone.utc),
        reason=reason,
    )


# =============================================================================
# Helper Unit Tests
# =============================================================================
def test_helper_has_oi_evaluation() -> None:
    """has_oi_evaluation discriminates OI tags and ignores substrings like POI."""
    assert not has_oi_evaluation(None)
    assert not has_oi_evaluation("")
    assert not has_oi_evaluation("Bullish Pinbar near POI and support")
    assert not has_oi_evaluation("Avoid choppy market")

    assert has_oi_evaluation("[REJECTED_OI] Contradictory OI")
    assert has_oi_evaluation("[OI_CONFLUENCE] Confirmed")
    assert has_oi_evaluation("[OI: Long Buildup]")
    assert has_oi_evaluation("Signal [Bullish Long Buildup: Δ1=+1.2%]")
    assert has_oi_evaluation("Signal [Warning: Short Covering squeeze +1.5%]")
    assert has_oi_evaluation("Signal [Warning: Long Liquidation flush -1.5%]")


def test_helper_has_funding_evaluation() -> None:
    """has_funding_evaluation detects exact funding tags."""
    assert not has_funding_evaluation(None)
    assert not has_funding_evaluation("Base pattern near POI")
    assert not has_funding_evaluation("Top Trader L/S (crowded long)")

    assert has_funding_evaluation("[REJECTED_FUNDING_CROWDED] Excessive funding")
    assert has_funding_evaluation("Base [CROWDED_LONG: funding 0.0800%]")
    assert has_funding_evaluation("Base [CROWDED_SHORT: funding -0.0800%]")


def test_helper_has_account_ratio_evaluation() -> None:
    """has_account_ratio_evaluation detects LS tags and avoids funding collisions."""
    assert not has_account_ratio_evaluation(None)
    assert not has_account_ratio_evaluation("Base pattern near POI")
    # CRITICAL: funding crowding must NOT trigger account ratio evaluation detection
    assert not has_account_ratio_evaluation("Base [CROWDED_LONG: funding 0.0800%]")
    assert not has_account_ratio_evaluation("Base [CROWDED_SHORT: funding -0.0800%]")

    assert has_account_ratio_evaluation("[REJECTED_LS_RATIO] Top Trader L/S 2.80")
    assert has_account_ratio_evaluation(
        "Base [Top Trader L/S 2.80 > max 2.50 (crowded long)]"
    )
    assert has_account_ratio_evaluation(
        "Base [Account L/S 0.20 < min 0.25 (crowded short)]"
    )


# =============================================================================
# Behavioral & Collision Regression Tests
# =============================================================================
def test_signal_engine_poi_reason_does_not_skip_oi() -> None:
    """Reason containing 'POI' must still execute Open Interest filter."""
    strategy = MockStrategy(
        initial_signal=_dummy_signal(reason="Bullish Pinbar at POI")
    )
    resolver = MockResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.BOTRAGRAM_ORIGIN,
        use_open_interest=True,
    )

    signal = engine.generate(candles=[_dummy_candle()])
    assert strategy.oi_calls == 1
    assert "Bullish Long Buildup" in (signal.reason or "")


def test_signal_engine_funding_crowded_long_does_not_skip_account_ratio() -> None:
    """Funding non-strict tag [CROWDED_LONG: ...] must NOT skip Account Ratio filter."""
    strategy = MockStrategy(
        initial_signal=_dummy_signal(reason="Base [CROWDED_LONG: funding 0.0800%]")
    )
    resolver = MockResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.BOTRAGRAM_ORIGIN,
        filter_account_ratio=True,
    )

    signal = engine.generate(candles=[_dummy_candle()])
    assert strategy.account_ratio_calls == 1
    assert "Top Trader L/S" in (signal.reason or "")


def test_signal_engine_funding_crowded_short_does_not_skip_account_ratio() -> None:
    """Funding non-strict [CROWDED_SHORT: ...] does NOT skip Account Ratio."""
    strategy = MockStrategy(
        initial_signal=_dummy_signal(reason="Base [CROWDED_SHORT: funding -0.0800%]")
    )
    resolver = MockResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.BOTRAGRAM_ORIGIN,
        filter_account_ratio=True,
    )

    signal = engine.generate(candles=[_dummy_candle()])
    assert strategy.account_ratio_calls == 1
    assert "Top Trader L/S" in (signal.reason or "")


def test_signal_engine_skips_already_evaluated_oi() -> None:
    """Existing [REJECTED_OI] or OI evaluation in reason prevents second evaluation."""
    strategy = MockStrategy(
        initial_signal=_dummy_signal(reason="[REJECTED_OI] Contradictory OI in BUY")
    )
    resolver = MockResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.BOTRAGRAM_ORIGIN,
        use_open_interest=True,
    )

    engine.generate(candles=[_dummy_candle()])
    assert strategy.oi_calls == 0


def test_signal_engine_skips_already_evaluated_funding() -> None:
    """Existing [REJECTED_FUNDING_CROWDED] prevents second funding evaluation."""
    strategy = MockStrategy(
        initial_signal=_dummy_signal(
            reason="[REJECTED_FUNDING_CROWDED] Excessive long funding"
        )
    )
    resolver = MockResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.BOTRAGRAM_ORIGIN,
        filter_funding_sentiment=True,
    )

    engine.generate(candles=[_dummy_candle()])
    assert strategy.funding_calls == 0


def test_signal_engine_skips_already_evaluated_account_ratio() -> None:
    """Existing [REJECTED_LS_RATIO] prevents second account ratio evaluation."""
    strategy = MockStrategy(
        initial_signal=_dummy_signal(
            reason="[REJECTED_LS_RATIO] Top Trader long ratio crowded"
        )
    )
    resolver = MockResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.BOTRAGRAM_ORIGIN,
        filter_account_ratio=True,
    )

    engine.generate(candles=[_dummy_candle()])
    assert strategy.account_ratio_calls == 0


def test_signal_engine_chains_all_filters_once() -> None:
    """Enabling all filters evaluates each filter exactly once."""
    strategy = MockStrategy(initial_signal=_dummy_signal(reason="Clean Origin Setup"))
    resolver = MockResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.BOTRAGRAM_ORIGIN,
        use_open_interest=True,
        filter_funding_sentiment=True,
        filter_account_ratio=True,
    )

    signal = engine.generate(candles=[_dummy_candle()])
    assert strategy.oi_calls == 1
    assert strategy.funding_calls == 1
    assert strategy.account_ratio_calls == 1

    reason = signal.reason or ""
    assert "Bullish Long Buildup" in reason
    assert "CROWDED_LONG" in reason
    assert "Top Trader L/S" in reason


def test_signal_engine_hold_signals_unaffected() -> None:
    """HOLD signals bypass all downstream filter evaluations."""
    strategy = MockStrategy(
        initial_signal=_dummy_signal(signal_type=SignalType.HOLD, reason="Neutral hold")
    )
    resolver = MockResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.BOTRAGRAM_ORIGIN,
        use_open_interest=True,
        filter_funding_sentiment=True,
        filter_account_ratio=True,
    )

    signal = engine.generate(candles=[_dummy_candle()])
    assert signal.signal_type is SignalType.HOLD
    assert strategy.oi_calls == 0
    assert strategy.funding_calls == 0
    assert strategy.account_ratio_calls == 0
