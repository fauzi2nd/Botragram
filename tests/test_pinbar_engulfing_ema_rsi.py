"""
Botragram

Description:
    Unit tests for PinbarEngulfingEmaRsiStrategy.

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
from datetime import UTC, datetime, timedelta
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
from botragram.strategies.factory import StrategyFactory
from botragram.strategies.price_action import PinbarEngulfingEmaRsiStrategy

_START_TIME = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def _make_candle(
    *,
    index: int,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
    volume: Decimal = Decimal("100.0"),
) -> Candle:
    """Helper to generate a timestamped Candle for testing."""
    open_time = _START_TIME + timedelta(minutes=15 * index)
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M15,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
    )


def test_strategy_parameter_validation() -> None:
    """Validate parameter boundaries on strategy initialization."""
    with pytest.raises(ValueError, match="EMA trend and pullback periods"):
        PinbarEngulfingEmaRsiStrategy(trend_period=0)

    with pytest.raises(ValueError, match="Pullback period must be smaller"):
        PinbarEngulfingEmaRsiStrategy(trend_period=21, pullback_period=21)

    with pytest.raises(ValueError, match="RSI long thresholds"):
        PinbarEngulfingEmaRsiStrategy(
            rsi_long_min=Decimal("60.0"), rsi_long_max=Decimal("50.0")
        )

    with pytest.raises(ValueError, match="Minimum wick ratio"):
        PinbarEngulfingEmaRsiStrategy(min_wick_ratio=Decimal("0.0"))


def test_factory_resolves_pinbar_engulfing_strategy() -> None:
    """Ensure StrategyFactory constructs PinbarEngulfingEmaRsiStrategy properly."""
    settings = StrategySettings(
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
        pier_trend_period=100,
        pier_pullback_period=20,
    )
    strategy = StrategyFactory.create(settings=settings)

    assert isinstance(strategy, PinbarEngulfingEmaRsiStrategy)
    assert strategy.strategy_type is StrategyType.PINBAR_ENGULFING_EMA_RSI
    assert strategy.trend_period == 100
    assert strategy.pullback_period == 20


def test_generate_bullish_pinbar_signal_in_uptrend() -> None:
    """Trigger a BUY signal when a bullish pinbar bounces from EMA in an uptrend."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
    )

    candles: list[Candle] = []
    # Build an uptrend series of 45 candles
    base = Decimal("100.0")
    for i in range(45):
        price = base + Decimal(str(i * 1.0))
        candles.append(
            _make_candle(
                index=i,
                open_price=price,
                high_price=price + Decimal("1.5"),
                low_price=price - Decimal("0.5"),
                close_price=price + Decimal("0.8"),
                volume=Decimal("100.0"),
            )
        )

    # 10 pullback candles to cool down RSI into 35-52 zone near EMA10
    for i in range(45, 55):
        prev_close = candles[-1].close_price
        candles.append(
            _make_candle(
                index=i,
                open_price=prev_close,
                high_price=prev_close + Decimal("0.2"),
                low_price=prev_close - Decimal("1.5"),
                close_price=prev_close - Decimal("1.2"),
                volume=Decimal("100.0"),
            )
        )

    # Candle 55: Bullish Pinbar (Hammer) bouncing near EMA10 with elevated volume
    last_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=55,
            open_price=last_close,
            high_price=last_close + Decimal("0.8"),
            low_price=last_close - Decimal("8.0"),  # Long rejection wick
            close_price=last_close + Decimal("0.5"),
            volume=Decimal("250.0"),  # > 1.1x volume SMA
        )
    )

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.BUY
    assert signal.confidence >= Decimal("0.65")
    assert "Bullish Pinbar" in (signal.reason or "")


def test_generate_bearish_engulfing_signal_in_downtrend() -> None:
    """Trigger a SELL signal when a bearish engulfing pattern forms in downtrend."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
        rsi_short_min=Decimal("40.0"),
        rsi_short_max=Decimal("70.0"),
    )

    candles: list[Candle] = []
    # Build a downtrend series of 45 candles
    base = Decimal("200.0")
    for i in range(45):
        price = base - Decimal(str(i * 1.0))
        candles.append(
            _make_candle(
                index=i,
                open_price=price,
                high_price=price + Decimal("0.5"),
                low_price=price - Decimal("1.5"),
                close_price=price - Decimal("0.8"),
                volume=Decimal("100.0"),
            )
        )

    # 10 rally/pullback candles to elevate RSI into 48-65 zone near EMA10
    for i in range(45, 55):
        prev_close = candles[-1].close_price
        candles.append(
            _make_candle(
                index=i,
                open_price=prev_close,
                high_price=prev_close + Decimal("1.5"),
                low_price=prev_close - Decimal("0.2"),
                close_price=prev_close + Decimal("1.2"),
                volume=Decimal("100.0"),
            )
        )

    # Candle 55: Bearish Engulfing candle covering candle 54
    last_candle = candles[-1]
    engulf_open = last_candle.close_price + Decimal("0.5")
    candles.append(
        _make_candle(
            index=55,
            open_price=engulf_open,
            high_price=engulf_open + Decimal("0.5"),
            low_price=last_candle.open_price - Decimal("2.0"),
            close_price=last_candle.open_price - Decimal("1.5"),  # Engulfs prev body
            volume=Decimal("250.0"),
        )
    )

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.SELL
    assert signal.confidence >= Decimal("0.65")
    assert "Bearish Engulfing" in (signal.reason or "")


def test_hold_when_pattern_is_counter_trend() -> None:
    """Reject long setup when price is below macro trend EMA."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
    )

    candles: list[Candle] = []
    # Strong downtrend
    base = Decimal("200.0")
    for i in range(59):
        price = base - Decimal(str(i * 2.0))
        candles.append(
            _make_candle(
                index=i,
                open_price=price,
                high_price=price + Decimal("1.0"),
                low_price=price - Decimal("2.0"),
                close_price=price - Decimal("1.0"),
                volume=Decimal("100.0"),
            )
        )

    # Candle 59: Bullish pinbar appearing in deep downtrend (counter-trend)
    curr_level = candles[-1].close_price
    candles.append(
        _make_candle(
            index=59,
            open_price=curr_level,
            high_price=curr_level + Decimal("1.0"),
            low_price=curr_level - Decimal("8.0"),
            close_price=curr_level + Decimal("0.8"),
            volume=Decimal("250.0"),
        )
    )

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.HOLD
    assert signal.confidence == Decimal("0")


def test_hold_when_pattern_floats_mid_range() -> None:
    """Reject setup when candlestick pattern floats far from key levels."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
        require_key_level_location=True,
        location_tolerance_pct=Decimal("0.01"),  # Tight 1% tolerance
    )

    candles: list[Candle] = []
    base = Decimal("100.0")
    for i in range(54):
        price = base + Decimal(str(i * 1.0))
        candles.append(
            _make_candle(
                index=i,
                open_price=price,
                high_price=price + Decimal("1.5"),
                low_price=price - Decimal("0.5"),
                close_price=price + Decimal("0.8"),
                volume=Decimal("100.0"),
            )
        )

    # Trigger candle that is far above EMA10 (floating mid-air in range gap)
    last_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=54,
            open_price=last_close + Decimal("15.0"),
            high_price=last_close + Decimal("16.0"),
            low_price=last_close + Decimal("8.0"),  # Low is 8 points above EMA
            close_price=last_close + Decimal("15.5"),
            volume=Decimal("250.0"),
        )
    )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert signal.confidence == Decimal("0")


def test_hold_when_natr_below_threshold() -> None:
    """Reject setup when volatility NATR is below minimum threshold."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        min_natr_threshold=Decimal("0.05"),  # high threshold to force rejection
    )

    candles: list[Candle] = []
    base = Decimal("100.0")
    for i in range(60):
        price = base + Decimal(str(i * 0.1))
        candles.append(
            _make_candle(
                index=i,
                open_price=price,
                high_price=price + Decimal("0.05"),
                low_price=price - Decimal("0.05"),
                close_price=price,
                volume=Decimal("100.0"),
            )
        )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "Dead market volatility rejected" in (signal.reason or "")
