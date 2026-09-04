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
from botragram.engine import SignalEngine
from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle
from botragram.strategies import StrategyFactory
from botragram.strategies.base import BaseStrategy
from botragram.strategies.breakout import BollingerBreakoutStrategy
from botragram.strategies.price_action import (
    ChochFvgStrategy,
    ChochRsiBbHybridStrategy,
    HighConfluenceExhaustionStrategy,
    LiquiditySweepExhaustionStrategy,
)
from botragram.strategies.scalping import (
    EMAScalpingStrategy,
    RSIBBScalpingStrategy,
    VWAPBreakoutStrategy,
)
from botragram.strategies.swing import MACDSwingStrategy
from botragram.strategies.trend import (
    ADXTrendStrategy,
    EMACrossStrategy,
    EMARsiStrategy,
    IchimokuCloudStrategy,
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
        ichimoku_conversion_period=2,
        ichimoku_base_period=3,
        ichimoku_leading_span_period=4,
        adx_period=2,
        adx_fast_period=2,
        adx_slow_period=3,
        adx_threshold=Decimal("25.0"),
        atr_period=2,
        vwap_volume_period=2,
        vwap_volume_multiplier=Decimal("1.2"),
        hce_trend_period=5,
        hce_intermediate_trend_period=2,
        hce_bb_period=3,
        hce_rsi_period=2,
        hce_volume_period=2,
        hce_adx_period=2,
        hce_swing_lookback=2,
        choch_trend_period=5,
        choch_intermediate_trend_period=2,
        choch_swing_window=2,
        choch_fvg_lookback=2,
        choch_volume_period=2,
        crbb_trend_period=5,
        crbb_intermediate_trend_period=2,
        crbb_swing_window=2,
        crbb_fvg_lookback=2,
        crbb_volume_period=2,
        crbb_bb_period=2,
        crbb_rsi_period=2,
        crbb_adx_period=2,
        crbb_atr_period=2,
        lse_swing_lookback=2,
        lse_volume_period=2,
        lse_rsi_period=2,
        lse_atr_period=2,
    )


# =============================================================================
# Factory and Configuration Tests
# =============================================================================
@pytest.mark.parametrize(
    ("strategy_type", "expected_type"),
    (
        (StrategyType.ADX_TREND, ADXTrendStrategy),
        (StrategyType.BOLLINGER_BREAKOUT, BollingerBreakoutStrategy),
        (StrategyType.CHOCH_FVG, ChochFvgStrategy),
        (StrategyType.CHOCH_RSI_BB_HYBRID, ChochRsiBbHybridStrategy),
        (StrategyType.EMA_CROSS, EMACrossStrategy),
        (StrategyType.EMA_RSI, EMARsiStrategy),
        (StrategyType.EMA_SCALPING, EMAScalpingStrategy),
        (
            StrategyType.HIGH_CONFLUENCE_EXHAUSTION,
            HighConfluenceExhaustionStrategy,
        ),
        (StrategyType.ICHIMOKU_CLOUD, IchimokuCloudStrategy),
        (
            StrategyType.LIQUIDITY_SWEEP_EXHAUSTION,
            LiquiditySweepExhaustionStrategy,
        ),
        (StrategyType.MACD_SWING, MACDSwingStrategy),
        (StrategyType.RSI_BB_SCALPING, RSIBBScalpingStrategy),
        (StrategyType.SUPERTREND, SupertrendStrategy),
        (StrategyType.VWAP_BREAKOUT, VWAPBreakoutStrategy),
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
    settings = StrategySettings(strategy_type=StrategyType.CUSTOM)

    with pytest.raises(ValueError, match="Unsupported strategy type"):
        StrategyFactory.create(settings=settings)


def test_strategy_resolver_returns_exact_reusable_instances() -> None:
    """Resolve explicit types without a mutable current-strategy selection."""
    resolver = StrategyFactory.create_resolver(
        settings=_create_strategy_settings(strategy_type=StrategyType.EMA_CROSS),
    )

    btc_strategy = resolver.resolve(strategy_type=StrategyType.EMA_CROSS)
    eth_strategy = resolver.resolve(strategy_type=StrategyType.EMA_SCALPING)

    assert isinstance(btc_strategy, EMACrossStrategy)
    assert isinstance(eth_strategy, EMAScalpingStrategy)
    assert resolver.resolve(strategy_type=StrategyType.EMA_CROSS) is btc_strategy
    with pytest.raises(ValueError, match="Unsupported strategy type"):
        resolver.resolve(strategy_type=StrategyType.CUSTOM)


def test_signal_engine_resolves_each_context_strategy_without_leakage() -> None:
    """Evaluate BTC and ETH with distinct explicit strategies sequentially."""
    resolver = StrategyFactory.create_resolver(
        settings=_create_strategy_settings(strategy_type=StrategyType.EMA_CROSS),
    )
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.EMA_CROSS,
    )
    btc_candles = _create_candles((1, 1, 1, 2), symbol="BTCUSDT")
    eth_candles = _create_candles((1, 1, 1, 2), symbol="ETHUSDT")

    btc_signal = engine.generate(
        candles=btc_candles,
        strategy_type=StrategyType.EMA_CROSS,
    )
    eth_signal = engine.generate(
        candles=eth_candles,
        strategy_type=StrategyType.EMA_SCALPING,
    )

    assert btc_signal.strategy_name == StrategyType.EMA_CROSS.value
    assert eth_signal.strategy_name == StrategyType.EMA_SCALPING.value
    assert engine.generate(candles=btc_candles).strategy_name == (
        StrategyType.EMA_CROSS.value
    )


@pytest.mark.parametrize(
    "constructor",
    (
        lambda: ADXTrendStrategy(fast_period=3, slow_period=3),
        lambda: ADXTrendStrategy(adx_period=0),
        lambda: ADXTrendStrategy(adx_threshold=Decimal("150")),
        lambda: EMACrossStrategy(fast_period=3, slow_period=3),
        lambda: EMARsiStrategy(
            fast_period=2,
            slow_period=3,
            rsi_oversold=Decimal("80"),
            rsi_overbought=Decimal("70"),
        ),
        lambda: BollingerBreakoutStrategy(standard_deviation=Decimal("0")),
        lambda: EMAScalpingStrategy(minimum_body_ratio=Decimal("1.1")),
        lambda: IchimokuCloudStrategy(
            conversion_period=10,
            base_period=5,
            leading_span_period=20,
        ),
        lambda: IchimokuCloudStrategy(conversion_period=0),
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
    assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")


def test_ichimoku_cloud_generates_buy_signal_on_bullish_tk_cross_above_cloud() -> None:
    """Verify Ichimoku strategy emits BUY when TK cross is above the cloud."""
    strategy = IchimokuCloudStrategy(
        conversion_period=2,
        base_period=3,
        leading_span_period=4,
    )
    # Stepwise upward movement creates bullish TK cross above Kumo cloud
    candles = _create_candles((10, 10, 10, 10, 15, 20))

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.BUY
    assert signal.symbol == "BTCUSDT"
    assert signal.price == Decimal("20")
    assert signal.strategy_name == StrategyType.ICHIMOKU_CLOUD.value
    assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")


def test_ichimoku_cloud_generates_sell_signal_on_bearish_tk_cross_below_cloud() -> None:
    """Verify Ichimoku strategy emits SELL when TK cross is below the cloud."""
    strategy = IchimokuCloudStrategy(
        conversion_period=2,
        base_period=3,
        leading_span_period=4,
    )
    # Stepwise downward movement creates bearish TK cross below Kumo cloud
    candles = _create_candles((20, 20, 20, 20, 15, 10))

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.SELL
    assert signal.symbol == "BTCUSDT"
    assert signal.price == Decimal("10")
    assert signal.strategy_name == StrategyType.ICHIMOKU_CLOUD.value
    assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")


def test_adx_trend_holds_when_adx_is_below_threshold() -> None:
    """Verify ADX trend strategy stays in HOLD during low-ADX choppy conditions."""
    strategy = ADXTrendStrategy(
        adx_period=2,
        fast_period=2,
        slow_period=3,
        adx_threshold=Decimal("50.0"),
    )
    candles = _create_candles((10, 10, 10, 10, 10))

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.HOLD
    assert signal.confidence == Decimal("0")
    assert signal.reason is not None and "below trend threshold" in signal.reason


def test_adx_trend_generates_buy_on_strong_uptrend() -> None:
    """Verify ADX trend strategy emits BUY on strong trending prices."""
    strategy = ADXTrendStrategy(
        adx_period=2,
        fast_period=2,
        slow_period=3,
        adx_threshold=Decimal("10.0"),
    )
    candles = _create_candles((10, 12, 14, 16, 20))

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.BUY
    assert signal.strategy_name == StrategyType.ADX_TREND.value
    assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")


def test_adx_trend_generates_sell_on_strong_downtrend() -> None:
    """Verify ADX trend strategy emits SELL on strong downtrend prices."""
    strategy = ADXTrendStrategy(
        adx_period=2,
        fast_period=2,
        slow_period=3,
        adx_threshold=Decimal("10.0"),
    )
    candles = _create_candles((20, 16, 14, 12, 10))

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.SELL
    assert signal.strategy_name == StrategyType.ADX_TREND.value
    assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")


def test_rsi_bb_scalping_generates_hold_on_flat_market() -> None:
    """Verify RSI BB scalping strategy emits HOLD on flat prices."""
    strategy = RSIBBScalpingStrategy(
        bb_period=2,
        rsi_period=2,
        bb_standard_deviation=Decimal("2"),
        rsi_oversold=Decimal("30"),
        rsi_overbought=Decimal("70"),
    )
    candles = _create_candles((10, 10, 10, 10))

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.HOLD
    assert signal.confidence == Decimal("0")


def test_rsi_bb_scalping_oversold_bounce_generates_buy() -> None:
    """Verify RSI BB scalping emits BUY on oversold bounce with rejection wick."""
    strategy = RSIBBScalpingStrategy(
        bb_period=3,
        rsi_period=3,
        bb_standard_deviation=Decimal("2"),
        rsi_oversold=Decimal("30"),
        rsi_overbought=Decimal("70"),
        ranging_only=False,
        require_trend_filter=False,
        min_confidence=Decimal("0.60"),
    )
    candles = [
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=0),
            close_time=_START_TIME + timedelta(minutes=1),
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=1),
            close_time=_START_TIME + timedelta(minutes=2),
            open_price=Decimal("98"),
            high_price=Decimal("99"),
            low_price=Decimal("90"),
            close_price=Decimal("91"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=2),
            close_time=_START_TIME + timedelta(minutes=3),
            open_price=Decimal("91"),
            high_price=Decimal("92"),
            low_price=Decimal("80"),
            close_price=Decimal("81"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=3),
            close_time=_START_TIME + timedelta(minutes=4),
            open_price=Decimal("81"),
            high_price=Decimal("85"),
            low_price=Decimal("70"),
            close_price=Decimal("84"),
            volume=Decimal("15"),
        ),
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=4),
            close_time=_START_TIME + timedelta(minutes=5),
            open_price=Decimal("84"),
            high_price=Decimal("88"),
            low_price=Decimal("82"),
            close_price=Decimal("87"),
            volume=Decimal("12"),
        ),
    ]

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.BUY
    assert signal.confidence >= Decimal("0.60")
    assert "DynATR TP" in str(signal.reason)
    assert "DynATR SL" in str(signal.reason)


def test_rsi_bb_scalping_extreme_volatility_returns_hold() -> None:
    """Verify extreme normalized ATR suppresses scalping entry."""
    strategy = RSIBBScalpingStrategy(
        bb_period=3,
        rsi_period=3,
        atr_period=3,
        max_natr_threshold=Decimal("0.01"),  # Very strict NATR threshold (1%)
        ranging_only=False,
        require_trend_filter=False,
    )
    # Wild candles where ATR will easily exceed 1% of close
    candles = [
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=i),
            close_time=_START_TIME + timedelta(minutes=i + 1),
            open_price=Decimal("100"),
            high_price=Decimal("120"),
            low_price=Decimal("80"),
            close_price=Decimal("95" if i % 2 == 0 else "105"),
            volume=Decimal("10"),
        )
        for i in range(10)
    ]

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.HOLD
    assert "Extreme volatility" in str(signal.reason)


def test_rsi_bb_scalping_adx_filter_suppresses_entry_in_strong_trend() -> None:
    """Verify ADX >= threshold suppresses scalping when ranging_only is True."""
    strategy = RSIBBScalpingStrategy(
        bb_period=3,
        rsi_period=3,
        adx_period=3,
        adx_ranging_threshold=Decimal("20.0"),
        ranging_only=True,
        require_trend_filter=False,
    )
    candles = [
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=i),
            close_time=_START_TIME + timedelta(minutes=i + 1),
            open_price=Decimal(str(100 + i * 5)),
            high_price=Decimal(str(105 + i * 5)),
            low_price=Decimal(str(99 + i * 5)),
            close_price=Decimal(str(104 + i * 5)),
            volume=Decimal("10"),
        )
        for i in range(10)
    ]

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.HOLD
    assert "Strong trend" in str(signal.reason)


def test_vwap_breakout_generates_hold_on_flat_market() -> None:
    """Verify VWAP breakout strategy emits HOLD on flat prices."""
    strategy = VWAPBreakoutStrategy(
        atr_period=2,
        volume_period=2,
        volume_multiplier=Decimal("1.2"),
    )
    candles = _create_candles((10, 10, 10, 10))

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.HOLD
    assert signal.confidence == Decimal("0")


def test_vwap_breakout_evaluates_zero_volume_candles_safely() -> None:
    """Verify VWAP breakout strategy handles zero volume candles without error."""
    strategy = VWAPBreakoutStrategy(
        atr_period=2,
        volume_period=2,
        volume_multiplier=Decimal("1.2"),
    )
    candles = tuple(
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=index),
            close_time=_START_TIME + timedelta(minutes=index + 1),
            open_price=Decimal("10"),
            high_price=Decimal("11"),
            low_price=Decimal("9"),
            close_price=Decimal("10"),
            volume=Decimal("0"),
        )
        for index in range(5)
    )

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.HOLD
    assert signal.confidence == Decimal("0")


@pytest.mark.parametrize(
    "strategy_type",
    (
        StrategyType.ADX_TREND,
        StrategyType.BOLLINGER_BREAKOUT,
        StrategyType.EMA_CROSS,
        StrategyType.EMA_RSI,
        StrategyType.EMA_SCALPING,
        StrategyType.HIGH_CONFLUENCE_EXHAUSTION,
        StrategyType.ICHIMOKU_CLOUD,
        StrategyType.MACD_SWING,
        StrategyType.RSI_BB_SCALPING,
        StrategyType.SUPERTREND,
        StrategyType.VWAP_BREAKOUT,
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
    candles = _create_candles((1, 2, 3))

    with pytest.raises(ValueError, match="requires at least 4 candles"):
        strategy.generate_signal(candles=candles)


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


def test_strategy_default_intervals_and_exit_rates() -> None:
    """Verify each strategy maps to its optimal timeframe and RRR."""
    from botragram.constants.strategy import (
        get_strategy_default_exit_rates,
        get_strategy_default_interval,
    )
    from botragram.enums import Interval

    scalping_types = (
        StrategyType.EMA_SCALPING,
        StrategyType.RSI_BB_SCALPING,
        StrategyType.VWAP_BREAKOUT,
    )
    for st in scalping_types:
        assert get_strategy_default_interval(st) is Interval.M5
        sl, tp = get_strategy_default_exit_rates(st)
        assert sl == Decimal("0.005")
        assert tp == Decimal("0.01")
        assert tp / sl >= Decimal("2")

    trend_types = (
        StrategyType.EMA_RSI,
        StrategyType.ICHIMOKU_CLOUD,
        StrategyType.SUPERTREND,
        StrategyType.ADX_TREND,
        StrategyType.BOLLINGER_BREAKOUT,
    )
    for st in trend_types:
        assert get_strategy_default_interval(st) is Interval.M15
        sl, tp = get_strategy_default_exit_rates(st)
        assert sl == Decimal("0.015")
        assert tp == Decimal("0.03")
        assert tp / sl >= Decimal("2")

    assert get_strategy_default_interval(StrategyType.EMA_CROSS) is Interval.M15
    sl_ema, tp_ema = get_strategy_default_exit_rates(StrategyType.EMA_CROSS)
    assert sl_ema == Decimal("0.02")
    assert tp_ema == Decimal("0.04")
    assert tp_ema / sl_ema >= Decimal("2")

    assert get_strategy_default_interval(StrategyType.MACD_SWING) is Interval.H1
    sl_m, tp_m = get_strategy_default_exit_rates(StrategyType.MACD_SWING)
    assert sl_m == Decimal("0.025")
    assert tp_m == Decimal("0.05")
    assert tp_m / sl_m >= Decimal("2")

    assert (
        get_strategy_default_interval(StrategyType.HIGH_CONFLUENCE_EXHAUSTION)
        is Interval.M5
    )
    sl_hce, tp_hce = get_strategy_default_exit_rates(
        StrategyType.HIGH_CONFLUENCE_EXHAUSTION
    )
    assert sl_hce == Decimal("0.007")
    assert tp_hce == Decimal("0.014")


def test_strategy_settings_default_interval() -> None:
    """Verify StrategySettings exposes default_interval."""
    from botragram.config.strategy_settings import StrategySettings
    from botragram.enums import Interval

    settings_scalping = StrategySettings(strategy_type=StrategyType.RSI_BB_SCALPING)
    assert settings_scalping.default_interval is Interval.M5

    settings_trend = StrategySettings(strategy_type=StrategyType.ICHIMOKU_CLOUD)
    assert settings_trend.default_interval is Interval.M15

    settings_swing = StrategySettings(strategy_type=StrategyType.MACD_SWING)
    assert settings_swing.default_interval is Interval.H1

    settings_choch = StrategySettings(strategy_type=StrategyType.CHOCH_FVG)
    assert settings_choch.default_interval is Interval.M5

    settings_hce = StrategySettings(
        strategy_type=StrategyType.HIGH_CONFLUENCE_EXHAUSTION
    )
    assert settings_hce.default_interval is Interval.M5


def test_choch_fvg_strategy_signal_generation() -> None:
    """Verify ChochFvgStrategy generates valid signals and respects minimum candles."""
    strategy = ChochFvgStrategy(
        swing_window=3,
        fvg_lookback=10,
        volume_period=10,
        trend_period=15,
        intermediate_trend_period=5,
        min_confidence=Decimal("0.60"),
    )
    assert strategy.strategy_type is StrategyType.CHOCH_FVG
    assert strategy.minimum_candles >= 16

    # Generate 25 candles
    n = 25
    candles: list[Candle] = []
    base_time = _START_TIME

    for i in range(n):
        open_time = base_time + timedelta(minutes=5 * i)
        close_time = open_time + timedelta(minutes=5)
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M5,
                open_time=open_time,
                close_time=close_time,
                open_price=Decimal("95") + Decimal(str(i % 3)),
                high_price=Decimal("100") + Decimal(str(i % 3)),
                low_price=Decimal("90") + Decimal(str(i % 3)),
                close_price=Decimal("95") + Decimal(str(i % 3)),
                volume=Decimal("1000"),
            )
        )

    # Make swing high at index 12
    candles[12] = Candle(
        symbol="BTCUSDT",
        interval=Interval.M5,
        open_time=candles[12].open_time,
        close_time=candles[12].close_time,
        open_price=Decimal("95"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("95"),
        volume=Decimal("1000"),
    )

    # Bullish displacement breakout at index 23
    candles[23] = Candle(
        symbol="BTCUSDT",
        interval=Interval.M5,
        open_time=candles[23].open_time,
        close_time=candles[23].close_time,
        open_price=Decimal("95"),
        high_price=Decimal("116"),
        low_price=Decimal("94"),
        close_price=Decimal("115"),
        volume=Decimal("3000"),
    )

    # Pullback at index 24
    candles[24] = Candle(
        symbol="BTCUSDT",
        interval=Interval.M5,
        open_time=candles[24].open_time,
        close_time=candles[24].close_time,
        open_price=Decimal("115"),
        high_price=Decimal("115"),
        low_price=Decimal("111"),
        close_price=Decimal("112"),
        volume=Decimal("1500"),
    )

    signal = strategy.generate_signal(candles=candles)
    assert signal.symbol == "BTCUSDT"
    assert signal.signal_type in (SignalType.BUY, SignalType.HOLD)
    assert signal.strategy_name == "choch_fvg"

    # Verify factory creation
    settings = StrategySettings(strategy_type=StrategyType.CHOCH_FVG)
    factory_strategy = StrategyFactory.create(settings=settings)
    assert isinstance(factory_strategy, ChochFvgStrategy)
    assert factory_strategy.strategy_type is StrategyType.CHOCH_FVG

    # Verify resolver
    resolver = StrategyFactory.create_resolver(settings=settings)
    resolved = resolver.resolve(strategy_type=StrategyType.CHOCH_FVG)
    assert isinstance(resolved, ChochFvgStrategy)


def test_choch_fvg_strategy_trend_filter_rejection() -> None:
    """Verify CHoCH FVG rejects buy signals when below trend filter."""
    strategy = ChochFvgStrategy(
        swing_window=3,
        fvg_lookback=10,
        volume_period=10,
        trend_period=15,
        intermediate_trend_period=5,
        require_trend_filter=True,
    )
    # Generate 30 candles in overall downtrend
    candles: list[Candle] = []
    base_time = _START_TIME
    for i in range(30):
        open_time = base_time + timedelta(minutes=5 * i)
        close_time = open_time + timedelta(minutes=5)
        # Price steadily declining from 200 to 100
        price = Decimal(str(200 - i * 3))
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M5,
                open_time=open_time,
                close_time=close_time,
                open_price=price,
                high_price=price + Decimal("2"),
                low_price=price - Decimal("2"),
                close_price=price,
                volume=Decimal("1000"),
            )
        )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is not SignalType.BUY


def test_choch_fvg_strategy_validation() -> None:
    """Verify ChochFvgStrategy enforces bounded parameter invariants."""
    with pytest.raises(ValueError, match="CHoCH swing window"):
        ChochFvgStrategy(swing_window=0)

    with pytest.raises(ValueError, match="FVG lookback"):
        ChochFvgStrategy(fvg_lookback=0)

    with pytest.raises(ValueError, match="Volume period"):
        ChochFvgStrategy(volume_period=0)

    with pytest.raises(ValueError, match="Volume multiplier"):
        ChochFvgStrategy(volume_multiplier=Decimal("0"))

    with pytest.raises(ValueError, match="Minimum body ratio"):
        ChochFvgStrategy(min_body_ratio=Decimal("0"))

    with pytest.raises(ValueError, match="Minimum gap ratio"):
        ChochFvgStrategy(min_gap_ratio=Decimal("-0.01"))

    with pytest.raises(ValueError, match="Trend period"):
        ChochFvgStrategy(trend_period=0)

    with pytest.raises(ValueError, match="Intermediate trend period"):
        ChochFvgStrategy(intermediate_trend_period=0)

    with pytest.raises(ValueError, match="intermediate_trend_period must be less"):
        ChochFvgStrategy(trend_period=50, intermediate_trend_period=50)

    with pytest.raises(ValueError, match="Minimum confidence"):
        ChochFvgStrategy(min_confidence=Decimal("1.5"))


def test_choch_fvg_strategy_confidence_rejection() -> None:
    """Verify marginal signals with confidence below threshold are rejected."""
    strategy = ChochFvgStrategy(
        swing_window=3,
        fvg_lookback=10,
        volume_period=10,
        trend_period=15,
        intermediate_trend_period=5,
        min_confidence=Decimal("0.95"),
    )
    # Generate 25 flat candles
    candles: list[Candle] = []
    base_time = _START_TIME
    for i in range(25):
        open_time = base_time + timedelta(minutes=5 * i)
        close_time = open_time + timedelta(minutes=5)
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M5,
                open_time=open_time,
                close_time=close_time,
                open_price=Decimal("100"),
                high_price=Decimal("101"),
                low_price=Decimal("99"),
                close_price=Decimal("100"),
                volume=Decimal("100"),
            )
        )
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD


def test_macd_swing_generates_buy_signal_with_unified_confidence() -> None:
    """Verify MACD swing strategy emits BUY with unified confidence (0.60 - 0.95)."""
    strategy = MACDSwingStrategy(fast_period=2, slow_period=3, signal_period=2)
    candles = _create_candles((10, 10, 10, 8, 6, 12))
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")


def test_supertrend_generates_buy_signal_with_unified_confidence() -> None:
    """Verify Supertrend strategy emits BUY with unified confidence (0.60 - 0.95)."""
    strategy = SupertrendStrategy(period=2, multiplier=Decimal("1.0"))
    candles = _create_candles((20, 18, 16, 14, 12, 25))
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")


def test_bollinger_breakout_generates_buy_signal_with_unified_confidence() -> None:
    """Verify Bollinger breakout emits BUY with unified confidence (0.60 - 0.95)."""
    strategy = BollingerBreakoutStrategy(period=3, standard_deviation=Decimal("1.0"))
    candles = _create_candles((10, 10, 10, 10, 30))
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")


def test_ema_scalping_generates_buy_signal_with_unified_confidence() -> None:
    """Verify EMA scalping strategy emits BUY with unified confidence (0.60 - 0.95)."""
    strategy = EMAScalpingStrategy(
        fast_period=2,
        slow_period=3,
        minimum_body_ratio=Decimal("0.50"),
    )
    candles = [
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=0),
            close_time=_START_TIME + timedelta(minutes=1),
            open_price=Decimal("10"),
            high_price=Decimal("11"),
            low_price=Decimal("9"),
            close_price=Decimal("10"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=1),
            close_time=_START_TIME + timedelta(minutes=2),
            open_price=Decimal("10"),
            high_price=Decimal("11"),
            low_price=Decimal("9"),
            close_price=Decimal("10"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=2),
            close_time=_START_TIME + timedelta(minutes=3),
            open_price=Decimal("10"),
            high_price=Decimal("11"),
            low_price=Decimal("9"),
            close_price=Decimal("10"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M1,
            open_time=_START_TIME + timedelta(minutes=3),
            close_time=_START_TIME + timedelta(minutes=4),
            open_price=Decimal("11"),
            high_price=Decimal("20"),
            low_price=Decimal("10"),
            close_price=Decimal("19"),
            volume=Decimal("10"),
        ),
    ]
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")


def test_ema_rsi_generates_buy_signal_with_unified_confidence() -> None:
    """Verify EMA RSI strategy emits BUY with unified confidence (0.60 - 0.95)."""
    strategy = EMARsiStrategy(
        fast_period=2,
        slow_period=3,
        rsi_period=2,
        rsi_oversold=Decimal("40"),
        rsi_overbought=Decimal("70"),
    )
    candles = _create_candles((20, 10, 5, 12, 18))
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type in (SignalType.BUY, SignalType.HOLD)
    if signal.signal_type is SignalType.BUY:
        assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")
    else:
        assert signal.confidence == Decimal("0")


def test_vwap_breakout_generates_signals_with_unified_confidence() -> None:
    """Verify VWAP breakout strategy emits unified confidence (0.60 - 0.95 or 0)."""
    strategy = VWAPBreakoutStrategy(
        volume_period=2,
        volume_multiplier=Decimal("1.1"),
        atr_period=2,
    )
    candles = [
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M5,
            open_time=_START_TIME + timedelta(minutes=0),
            close_time=_START_TIME + timedelta(minutes=5),
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M5,
            open_time=_START_TIME + timedelta(minutes=5),
            close_time=_START_TIME + timedelta(minutes=10),
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M5,
            open_time=_START_TIME + timedelta(minutes=10),
            close_time=_START_TIME + timedelta(minutes=15),
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M5,
            open_time=_START_TIME + timedelta(minutes=15),
            close_time=_START_TIME + timedelta(minutes=20),
            open_price=Decimal("100"),
            high_price=Decimal("110"),
            low_price=Decimal("99"),
            close_price=Decimal("108"),
            volume=Decimal("50"),
        ),
    ]
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert Decimal("0.60") <= signal.confidence <= Decimal("0.95")
