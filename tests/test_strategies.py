"""
Botragram

Description:
    Trading strategy contract and signal generation tests.

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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.strategy_settings import StrategySettings
from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle
from botragram.strategies import StrategyFactory
from botragram.strategies.base import BaseStrategy
from botragram.strategies.breakout import BollingerBreakoutStrategy
from botragram.strategies.scalping import EMAScalpingStrategy
from botragram.strategies.swing import MACDSwingStrategy
from botragram.strategies.trend import (
    EMACrossStrategy,
    EMARsiStrategy,
    SupertrendStrategy,
)

# =============================================================================
# Constants
# =============================================================================
_START_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


# =============================================================================
# Test Helpers
# =============================================================================
def _create_candles(
    closes: tuple[int | str, ...],
    *,
    symbol: str = "BTCUSDT",
) -> tuple[Candle, ...]:
    """Create valid, ordered candle fixtures from closing prices."""
    candles: list[Candle] = []

    for index, raw_close in enumerate(closes):
        close = Decimal(raw_close)
        open_time = _START_TIME + timedelta(minutes=index)

        candles.append(
            Candle(
                symbol=symbol,
                interval=Interval.M1,
                open_time=open_time,
                close_time=open_time + timedelta(minutes=1),
                open_price=close,
                high_price=close + Decimal("1"),
                low_price=close - Decimal("1"),
                close_price=close,
                volume=Decimal("1"),
            )
        )

    return tuple(candles)


def _create_strategy_settings(
    *,
    strategy_type: StrategyType,
) -> StrategySettings:
    """Create small-period settings suitable for deterministic tests."""
    return StrategySettings(
        strategy_type=strategy_type,
        fast_period=2,
        slow_period=3,
        rsi_period=2,
        bb_period=2,
        supertrend_period=2,
        scalping_fast_period=2,
        scalping_slow_period=3,
        macd_fast_period=2,
        macd_slow_period=3,
        macd_signal_period=2,
    )


# =============================================================================
# Factory and Configuration Tests
# =============================================================================
@pytest.mark.parametrize(
    ("strategy_type", "expected_type"),
    (
        (StrategyType.BOLLINGER_BREAKOUT, BollingerBreakoutStrategy),
        (StrategyType.EMA_CROSS, EMACrossStrategy),
        (StrategyType.EMA_RSI, EMARsiStrategy),
        (StrategyType.EMA_SCALPING, EMAScalpingStrategy),
        (StrategyType.MACD_SWING, MACDSwingStrategy),
        (StrategyType.SUPERTREND, SupertrendStrategy),
    ),
)
def test_strategy_factory_builds_each_supported_strategy(
    strategy_type: StrategyType,
    expected_type: type[BaseStrategy],
) -> None:
    """Verify factory output matches every supported strategy setting."""
    strategy = StrategyFactory.create(
        settings=_create_strategy_settings(strategy_type=strategy_type),
    )

    assert isinstance(strategy, expected_type)
    assert strategy.strategy_type is strategy_type


def test_strategy_factory_rejects_custom_without_an_implementation() -> None:
    """Verify unsupported custom strategy configuration fails explicitly."""
    with pytest.raises(ValueError, match="Unsupported strategy type"):
        StrategyFactory.create(
            settings=StrategySettings(strategy_type=StrategyType.CUSTOM),
        )


@pytest.mark.parametrize(
    "constructor",
    (
        lambda: EMACrossStrategy(fast_period=3, slow_period=3),
        lambda: EMARsiStrategy(
            fast_period=2,
            slow_period=3,
            rsi_oversold=Decimal("80"),
            rsi_overbought=Decimal("70"),
        ),
        lambda: BollingerBreakoutStrategy(standard_deviation=Decimal("0")),
        lambda: EMAScalpingStrategy(minimum_body_ratio=Decimal("1.1")),
        lambda: MACDSwingStrategy(fast_period=4, slow_period=3),
        lambda: SupertrendStrategy(period=0),
    ),
)
def test_strategies_reject_invalid_configuration(
    constructor: object,
) -> None:
    """Verify strategy invariants are checked during construction."""
    if not callable(constructor):
        raise AssertionError("Strategy constructor fixture must be callable")

    with pytest.raises(ValueError):
        constructor()


# =============================================================================
# Signal Generation Tests
# =============================================================================
def test_ema_cross_generates_buy_signal_on_latest_bullish_crossover() -> None:
    """Verify EMA crossover strategy emits a normalized buy signal."""
    strategy = EMACrossStrategy(fast_period=2, slow_period=3)
    candles = _create_candles((1, 1, 1, 2))

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.BUY
    assert signal.symbol == "BTCUSDT"
    assert signal.price == Decimal("2")
    assert signal.strategy_name == StrategyType.EMA_CROSS.value
    assert signal.generated_at == candles[-1].close_time
    assert Decimal("0") < signal.confidence <= Decimal("1")


@pytest.mark.parametrize(
    "strategy_type",
    (
        StrategyType.BOLLINGER_BREAKOUT,
        StrategyType.EMA_CROSS,
        StrategyType.EMA_RSI,
        StrategyType.EMA_SCALPING,
        StrategyType.MACD_SWING,
        StrategyType.SUPERTREND,
    ),
)
def test_each_strategy_can_evaluate_its_documented_minimum_candles(
    strategy_type: StrategyType,
) -> None:
    """Verify minimum_candles is sufficient for a complete evaluation."""
    strategy = StrategyFactory.create(
        settings=_create_strategy_settings(strategy_type=strategy_type),
    )
    candles = _create_candles(tuple("10" for _ in range(strategy.minimum_candles)))

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.HOLD
    assert signal.confidence == Decimal("0")


# =============================================================================
# Candle Validation Tests
# =============================================================================
def test_strategy_rejects_insufficient_candles() -> None:
    """Verify strategy evaluation enforces its minimum candle count."""
    strategy = EMACrossStrategy(fast_period=2, slow_period=3)

    with pytest.raises(ValueError, match="requires at least 4 candles"):
        strategy.generate_signal(candles=_create_candles((1, 2, 3)))


def test_strategy_rejects_mixed_symbols() -> None:
    """Verify one strategy evaluation cannot mix trading symbols."""
    strategy = EMACrossStrategy(fast_period=2, slow_period=3)
    btc_candles = _create_candles((1, 2, 3))
    eth_candle = _create_candles((4,), symbol="ETHUSDT")[0]

    with pytest.raises(ValueError, match="same trading symbol"):
        strategy.generate_signal(candles=(*btc_candles, eth_candle))


def test_strategy_rejects_non_chronological_candles() -> None:
    """Verify candle data must be strictly ordered by open time."""
    strategy = EMACrossStrategy(fast_period=2, slow_period=3)
    candles = _create_candles((1, 2, 3, 4))
    unordered = (candles[0], candles[2], candles[1], candles[3])

    with pytest.raises(ValueError, match="ordered from oldest to newest"):
        strategy.generate_signal(candles=unordered)
