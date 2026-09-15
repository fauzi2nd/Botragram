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
from botragram.indicators.price_action.candlesticks import (
    detect_engulfing,
    detect_pinbar,
    detect_star,
)
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


def test_min_sl_distance_pct_floor_enforced() -> None:
    """Enforce minimum stop-loss distance floor when candle wick is very tight."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
        min_sl_distance_pct=Decimal("0.010"),  # 1.0% minimum floor
        risk_reward_ratio=Decimal("2.0"),
    )

    candles: list[Candle] = []
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

    # Bullish pinbar with a tight lower wick (0.3% below close)
    last_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=55,
            open_price=last_close,
            high_price=last_close + Decimal("0.1"),
            low_price=last_close - Decimal("0.3"),
            close_price=last_close + Decimal("0.05"),
            volume=Decimal("250.0"),
        )
    )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert signal.reason is not None

    # Parse SL and TP from reason: "SL: <num> | TP: <num>"
    reason_parts = signal.reason.split("|")
    sl_str = reason_parts[-2].replace("SL:", "").strip()
    tp_str = reason_parts[-1].replace("TP:", "").strip()
    sl_val = Decimal(sl_str)
    tp_val = Decimal(tp_str)

    current_close = candles[-1].close_price
    sl_distance = current_close - sl_val
    expected_min_distance = current_close * Decimal("0.010")

    # The SL distance must be at least the 1.0% floor
    assert sl_distance >= expected_min_distance
    # TP must be exactly 2x the risk distance
    assert tp_val - current_close == sl_distance * Decimal("2.0")


def test_generate_morning_star_signal_in_uptrend() -> None:
    """Trigger a BUY signal when a Morning Star pattern forms in an uptrend."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
    )

    candles: list[Candle] = []
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

    for i in range(45, 53):
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

    # 3-bar Morning Star:
    # 53 (c1): Strong red candle
    c52_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=53,
            open_price=c52_close,
            high_price=c52_close + Decimal("0.2"),
            low_price=c52_close - Decimal("4.2"),
            close_price=c52_close - Decimal("4.0"),
            volume=Decimal("120.0"),
        )
    )
    # 54 (c2): Star candle (small body = 0.4, lower low probe)
    c53_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=54,
            open_price=c53_close - Decimal("0.2"),
            high_price=c53_close + Decimal("0.3"),
            low_price=c53_close - Decimal("1.5"),
            close_price=c53_close + Decimal("0.2"),
            volume=Decimal("130.0"),
        )
    )
    # 55 (c3): Strong green candle (penetrates > 50% into c1 body)
    c54_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=55,
            open_price=c54_close,
            high_price=c54_close + Decimal("3.8"),
            low_price=c54_close - Decimal("0.2"),
            close_price=c54_close + Decimal("3.5"),
            volume=Decimal("250.0"),
        )
    )

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.BUY
    assert signal.confidence >= Decimal("0.65")
    assert "Morning Star" in (signal.reason or "")


def test_generate_evening_star_signal_in_downtrend() -> None:
    """Trigger a SELL signal when an Evening Star pattern forms in a downtrend."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
    )

    candles: list[Candle] = []
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

    for i in range(45, 53):
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

    # 3-bar Evening Star:
    # 53 (c1): Strong green candle
    c52_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=53,
            open_price=c52_close,
            high_price=c52_close + Decimal("4.2"),
            low_price=c52_close - Decimal("0.2"),
            close_price=c52_close + Decimal("4.0"),
            volume=Decimal("120.0"),
        )
    )
    # 54 (c2): Star candle (small body = 0.4, higher high probe)
    c53_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=54,
            open_price=c53_close + Decimal("0.2"),
            high_price=c53_close + Decimal("1.5"),
            low_price=c53_close - Decimal("0.3"),
            close_price=c53_close - Decimal("0.2"),
            volume=Decimal("130.0"),
        )
    )
    # 55 (c3): Strong red candle (penetrates > 50% into c1 body)
    c54_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=55,
            open_price=c54_close,
            high_price=c54_close + Decimal("0.2"),
            low_price=c54_close - Decimal("3.8"),
            close_price=c54_close - Decimal("3.5"),
            volume=Decimal("250.0"),
        )
    )

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.SELL
    assert signal.confidence >= Decimal("0.65")
    assert "Evening Star" in (signal.reason or "")


def test_pinbar_rejection_in_ema200_dead_zone_buffer_emits_hold() -> None:
    """Verify setup near EMA200 within min_trend_distance_pct emits HOLD."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=5,
        pullback_period=3,
        rsi_period=3,
        volume_period=3,
        min_trend_distance_pct=Decimal("0.01"),  # 1% buffer
        require_key_level_location=False,
        use_macd=False,
        use_stoch_rsi=False,
    )
    # Price is 99.5, EMA is ~100 -> distance is 0.5% < 1% buffer
    candles = [
        _make_candle(
            index=i,
            open_price=Decimal("100.0"),
            high_price=Decimal("101.0"),
            low_price=Decimal("99.0"),
            close_price=Decimal("99.5"),
            volume=Decimal("100.0"),
        )
        for i in range(30)
    ]
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD


def test_pinbar_rejection_with_rsi_above_short_max_emits_hold() -> None:
    """Verify SELL setup is suppressed when RSI exceeds rsi_short_max (e.g. 55.0)."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=5,
        pullback_period=3,
        rsi_period=3,
        rsi_short_max=Decimal("55.0"),
        require_key_level_location=False,
        use_macd=False,
        use_stoch_rsi=False,
    )
    # Price steadily rising creates high RSI > 60
    candles = [
        _make_candle(
            index=i,
            open_price=Decimal(str(80 + i * 2)),
            high_price=Decimal(str(82 + i * 2)),
            low_price=Decimal(str(79 + i * 2)),
            close_price=Decimal(str(81 + i * 2)),
            volume=Decimal("100.0"),
        )
        for i in range(30)
    ]
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD


def test_strategy_macd_stoch_rsi_parameter_validation() -> None:
    """Validate MACD and Stoch RSI parameter bounds on initialization."""
    with pytest.raises(ValueError, match="MACD periods must be positive"):
        PinbarEngulfingEmaRsiStrategy(macd_fast_period=0)

    with pytest.raises(ValueError, match="MACD fast period must be less"):
        PinbarEngulfingEmaRsiStrategy(macd_fast_period=26, macd_slow_period=26)

    with pytest.raises(ValueError, match="Stoch RSI periods must be positive"):
        PinbarEngulfingEmaRsiStrategy(stoch_rsi_period=0)

    with pytest.raises(ValueError, match="Stoch RSI thresholds must be bounded"):
        PinbarEngulfingEmaRsiStrategy(
            stoch_rsi_oversold=Decimal("85.0"),
            stoch_rsi_overbought=Decimal("80.0"),
        )


def test_factory_creates_strategy_with_custom_macd_and_stoch_rsi() -> None:
    """Verify StrategyFactory configures MACD and Stoch RSI fields."""
    settings = StrategySettings(
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
        pier_use_macd=True,
        pier_macd_fast_period=10,
        pier_macd_slow_period=20,
        pier_macd_signal_period=7,
        pier_use_stoch_rsi=True,
        pier_stoch_rsi_period=12,
        pier_stoch_rsi_k_period=4,
        pier_stoch_rsi_d_period=4,
        pier_stoch_rsi_overbought=Decimal("75.0"),
        pier_stoch_rsi_oversold=Decimal("25.0"),
    )
    strategy = StrategyFactory.create(settings=settings)
    assert isinstance(strategy, PinbarEngulfingEmaRsiStrategy)
    assert strategy.use_macd is True
    assert strategy.macd_fast_period == 10
    assert strategy.macd_slow_period == 20
    assert strategy.macd_signal_period == 7
    assert strategy.use_stoch_rsi is True
    assert strategy.stoch_rsi_period == 12
    assert strategy.stoch_rsi_k_period == 4
    assert strategy.stoch_rsi_d_period == 4
    assert strategy.stoch_rsi_overbought == Decimal("75.0")
    assert strategy.stoch_rsi_oversold == Decimal("25.0")


def test_stoch_rsi_guard_suppresses_long_signal_when_overbought() -> None:
    """Verify BUY setup is rejected if Stoch RSI is above overbought limit."""
    base_strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
        stoch_rsi_oversold=Decimal("0.5"),
        stoch_rsi_overbought=Decimal("1.0"),
    )

    candles: list[Candle] = []
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

    last_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=55,
            open_price=last_close,
            high_price=last_close + Decimal("0.8"),
            low_price=last_close - Decimal("8.0"),
            close_price=last_close + Decimal("0.5"),
            volume=Decimal("250.0"),
        )
    )

    signal = base_strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD


def test_macd_guard_allows_valid_bounce_and_includes_context() -> None:
    """Verify BUY setup includes MACD and Stoch RSI context in signal reason."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
        use_macd=True,
        use_stoch_rsi=True,
    )

    candles: list[Candle] = []
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

    last_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=55,
            open_price=last_close,
            high_price=last_close + Decimal("0.8"),
            low_price=last_close - Decimal("8.0"),
            close_price=last_close + Decimal("0.5"),
            volume=Decimal("250.0"),
        )
    )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert "MACD_h=" in (signal.reason or "")
    assert "StochK=" in (signal.reason or "")


def test_candlestick_match_pattern_ratio_and_confidence() -> None:
    """Ensure pattern_ratio is cleanly populated and drives confidence bonus."""
    c_prev = _make_candle(
        index=0,
        open_price=Decimal("102.0"),
        high_price=Decimal("103.0"),
        low_price=Decimal("99.0"),
        close_price=Decimal("100.0"),  # body = 2.0
    )
    c_curr = _make_candle(
        index=1,
        open_price=Decimal("99.5"),
        high_price=Decimal("104.0"),
        low_price=Decimal("99.0"),
        close_price=Decimal("103.5"),  # body = 4.0 -> ratio = 2.0
    )

    engulfing = detect_engulfing(prev_candle=c_prev, curr_candle=c_curr)
    assert engulfing.matched is True
    assert engulfing.pattern_ratio == Decimal("2.0")
    assert engulfing.wick_ratio == Decimal("2.0")

    # Pinbar pattern_ratio test
    c_pinbar = _make_candle(
        index=2,
        open_price=Decimal("103.0"),
        high_price=Decimal("103.5"),
        low_price=Decimal("95.0"),
        close_price=Decimal("103.2"),
    )
    pinbar = detect_pinbar(candle=c_pinbar)
    assert pinbar.matched is True
    assert pinbar.pattern_ratio == pinbar.wick_ratio

    # Star pattern_ratio test
    c_star1 = _make_candle(
        index=3,
        open_price=Decimal("110.0"),
        high_price=Decimal("111.0"),
        low_price=Decimal("99.0"),
        close_price=Decimal("100.0"),
    )
    c_star2 = _make_candle(
        index=4,
        open_price=Decimal("98.0"),
        high_price=Decimal("99.0"),
        low_price=Decimal("97.0"),
        close_price=Decimal("98.5"),
    )
    c_star3 = _make_candle(
        index=5,
        open_price=Decimal("99.0"),
        high_price=Decimal("108.0"),
        low_price=Decimal("98.5"),
        close_price=Decimal("107.0"),
    )
    star = detect_star(
        first_candle=c_star1,
        second_candle=c_star2,
        third_candle=c_star3,
    )
    assert star.matched is True
    assert star.pattern_ratio == star.wick_ratio
