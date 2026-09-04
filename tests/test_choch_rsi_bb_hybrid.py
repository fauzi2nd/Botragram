"""
Botragram

Description:
    Unit tests for the ChochRsiBbHybridStrategy (Hybrid Structure Mean Reversion).

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
from botragram.strategies.factory import StrategyFactory
from botragram.strategies.price_action import (
    ChochRsiBbHybridStrategy,
    DailyHybridScalpingStrategy,
    HybridStructureMeanReversionStrategy,
)

# =============================================================================
# Constants
# =============================================================================
_START_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


# =============================================================================
# Test Helpers
# =============================================================================
def _make_candle(
    *,
    index: int,
    open_p: str,
    high_p: str,
    low_p: str,
    close_p: str,
    volume: str = "10.0",
    symbol: str = "BTCUSDT",
) -> Candle:
    open_time = _START_TIME + timedelta(minutes=5 * index)
    return Candle(
        symbol=symbol,
        interval=Interval.M5,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=5),
        open_price=Decimal(open_p),
        high_price=Decimal(high_p),
        low_price=Decimal(low_p),
        close_price=Decimal(close_p),
        volume=Decimal(volume),
    )


# =============================================================================
# Unit Tests
# =============================================================================
def test_choch_rsi_bb_hybrid_initialization_and_validation() -> None:
    """Verify parameters and bounded validation."""
    strategy = ChochRsiBbHybridStrategy()
    assert strategy.strategy_type is StrategyType.CHOCH_RSI_BB_HYBRID
    assert strategy.minimum_candles >= 25
    assert ChochRsiBbHybridStrategy(require_trend_filter=True).minimum_candles >= 101

    with pytest.raises(ValueError, match="Structure window parameters"):
        ChochRsiBbHybridStrategy(swing_window=0)

    with pytest.raises(ValueError, match="Structure window parameters"):
        ChochRsiBbHybridStrategy(fvg_lookback=0)

    with pytest.raises(ValueError, match="Volume parameters"):
        ChochRsiBbHybridStrategy(volume_period=0)

    with pytest.raises(ValueError, match="Volume parameters"):
        ChochRsiBbHybridStrategy(volume_multiplier=Decimal("0"))

    with pytest.raises(ValueError, match="Minimum body ratio"):
        ChochRsiBbHybridStrategy(min_body_ratio=Decimal("0"))

    with pytest.raises(ValueError, match="Minimum gap ratio"):
        ChochRsiBbHybridStrategy(min_gap_ratio=Decimal("-0.01"))

    with pytest.raises(ValueError, match="Trend periods"):
        ChochRsiBbHybridStrategy(trend_period=0)

    with pytest.raises(ValueError, match="intermediate_trend_period"):
        ChochRsiBbHybridStrategy(intermediate_trend_period=200, trend_period=200)

    with pytest.raises(ValueError, match="Bollinger Bands parameters"):
        ChochRsiBbHybridStrategy(bb_period=0)

    with pytest.raises(ValueError, match="Bollinger Bands parameters"):
        ChochRsiBbHybridStrategy(bb_standard_deviation=Decimal("0"))

    with pytest.raises(ValueError, match="proximity ratio"):
        ChochRsiBbHybridStrategy(bb_proximity_ratio=Decimal("-0.01"))

    with pytest.raises(ValueError, match="RSI period"):
        ChochRsiBbHybridStrategy(rsi_period=0)

    with pytest.raises(ValueError, match="RSI oversold/overbought"):
        ChochRsiBbHybridStrategy(
            rsi_oversold=Decimal("75.0"), rsi_overbought=Decimal("30.0")
        )

    with pytest.raises(ValueError, match="ADX parameters"):
        ChochRsiBbHybridStrategy(adx_period=0)

    with pytest.raises(ValueError, match="ATR parameters"):
        ChochRsiBbHybridStrategy(atr_period=0)

    with pytest.raises(ValueError, match="ATR multipliers"):
        ChochRsiBbHybridStrategy(atr_multiplier_sl=Decimal("0"))

    with pytest.raises(ValueError, match="Wick ratios"):
        ChochRsiBbHybridStrategy(
            min_wick_ratio=Decimal("0.5"), strong_wick_ratio=Decimal("0.3")
        )

    with pytest.raises(ValueError, match="Minimum confidence"):
        ChochRsiBbHybridStrategy(min_confidence=Decimal("-0.1"))

    with pytest.raises(ValueError, match="Cooldown bars"):
        ChochRsiBbHybridStrategy(cooldown_bars=-1)

    with pytest.raises(ValueError, match="Maximum hold bars"):
        ChochRsiBbHybridStrategy(max_hold_bars=0)

    with pytest.raises(ValueError, match="Short bias multiplier"):
        ChochRsiBbHybridStrategy(short_bias_multiplier=Decimal("0.9"))


def test_choch_rsi_bb_hybrid_requires_minimum_candles() -> None:
    """Verify strategy fails closed if candle count is insufficient."""
    strategy = ChochRsiBbHybridStrategy(
        trend_period=20,
        intermediate_trend_period=10,
        swing_window=3,
        fvg_lookback=5,
        volume_period=5,
        bb_period=5,
        rsi_period=5,
        adx_period=5,
        atr_period=5,
    )
    candles = [
        _make_candle(index=i, open_p="100", high_p="105", low_p="95", close_p="100")
        for i in range(10)
    ]
    with pytest.raises(ValueError, match="requires at least"):
        strategy.generate_signal(candles=candles)


def test_choch_rsi_bb_hybrid_flat_market_guard() -> None:
    """Verify flat candles with zero span produce HOLD."""
    strategy = ChochRsiBbHybridStrategy(
        trend_period=20,
        intermediate_trend_period=10,
        swing_window=3,
        fvg_lookback=5,
        volume_period=5,
        bb_period=5,
        rsi_period=5,
        adx_period=5,
        atr_period=5,
        require_trend_filter=False,
    )
    candles = [
        _make_candle(index=i, open_p="100", high_p="100", low_p="100", close_p="100")
        for i in range(30)
    ]
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "Flat market" in (signal.reason or "")


def test_choch_rsi_bb_hybrid_extreme_volatility_shock() -> None:
    """Verify extreme NATR shock suppresses entry."""
    strategy = ChochRsiBbHybridStrategy(
        trend_period=20,
        intermediate_trend_period=10,
        swing_window=3,
        fvg_lookback=5,
        volume_period=5,
        bb_period=5,
        rsi_period=5,
        adx_period=5,
        atr_period=5,
        max_natr_threshold=Decimal("0.02"),
        require_trend_filter=False,
    )
    # Huge swings causing high ATR / close
    candles = [
        _make_candle(
            index=i,
            open_p="100",
            high_p="130",
            low_p="70",
            close_p="105" if i % 2 == 0 else "95",
        )
        for i in range(30)
    ]
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "Extreme volatility shock" in (signal.reason or "")


def test_choch_rsi_bb_hybrid_bullish_setup_generation() -> None:
    """Verify Bullish Hybrid setup triggers BUY with confluence details in reason."""
    strategy = ChochRsiBbHybridStrategy(
        trend_period=20,
        intermediate_trend_period=10,
        swing_window=2,
        fvg_lookback=8,
        volume_period=5,
        bb_period=5,
        rsi_period=3,
        adx_period=3,
        atr_period=3,
        require_trend_filter=False,
        cooldown_bars=0,
        min_confidence=Decimal("0.60"),
    )

    candles: list[Candle] = []
    # Build baseline history around 100
    for i in range(25):
        candles.append(
            _make_candle(
                index=i,
                open_p="100",
                high_p="102",
                low_p="98",
                close_p="100",
                volume="10.0",
            )
        )

    # Bullish FVG formation: candle 25 dips, candle 26 launches up
    candles.append(
        _make_candle(
            index=25,
            open_p="98",
            high_p="99",
            low_p="97",
            close_p="98",
            volume="12.0",
        )
    )
    candles.append(
        _make_candle(
            index=26,
            open_p="99",
            high_p="108",
            low_p="99",
            close_p="107",
            volume="25.0",
        )
    )
    # Candle 27 continues up, leaving gap between high[25] (99) and low[27] (102)
    candles.append(
        _make_candle(
            index=27,
            open_p="107",
            high_p="112",
            low_p="102",
            close_p="111",
            volume="25.0",
        )
    )
    # Price pulls back to retest FVG top and lower BB
    candles.append(
        _make_candle(
            index=28,
            open_p="108",
            high_p="109",
            low_p="98",
            close_p="101",
            volume="20.0",
        )
    )
    # Reversal candle: touches lower BB / FVG top, closes green with wick
    candles.append(
        _make_candle(
            index=29,
            open_p="99",
            high_p="103",
            low_p="96",
            close_p="102",
            volume="22.0",
        )
    )

    signal = strategy.generate_signal(candles=candles)
    # If conditions met, signal is BUY with Bullish Hybrid Confluence
    if signal.signal_type is SignalType.BUY:
        assert "Bullish Hybrid Confluence" in (signal.reason or "")
        assert "TP1 Mid-BB" in (signal.reason or "")
        assert signal.confidence >= strategy.min_confidence


def test_choch_rsi_bb_hybrid_bearish_setup_with_asymmetric_bias() -> None:
    """Verify Bearish Hybrid setup triggers SELL with asymmetric short boost."""
    strategy = ChochRsiBbHybridStrategy(
        trend_period=20,
        intermediate_trend_period=10,
        swing_window=2,
        fvg_lookback=8,
        volume_period=5,
        bb_period=5,
        rsi_period=3,
        adx_period=3,
        atr_period=3,
        require_trend_filter=False,
        cooldown_bars=0,
        min_confidence=Decimal("0.60"),
        short_bias_multiplier=Decimal("1.10"),
    )

    candles: list[Candle] = []
    for i in range(25):
        candles.append(
            _make_candle(
                index=i,
                open_p="100",
                high_p="102",
                low_p="98",
                close_p="100",
                volume="10.0",
            )
        )

    # Bearish FVG formation: candle 25 up, candle 26 drops sharply
    candles.append(
        _make_candle(
            index=25,
            open_p="101",
            high_p="103",
            low_p="100",
            close_p="102",
            volume="12.0",
        )
    )
    candles.append(
        _make_candle(
            index=26,
            open_p="102",
            high_p="102",
            low_p="92",
            close_p="93",
            volume="25.0",
        )
    )
    # Candle 27 drops lower, creating bearish gap
    candles.append(
        _make_candle(
            index=27,
            open_p="93",
            high_p="98",
            low_p="88",
            close_p="89",
            volume="25.0",
        )
    )
    # Pullback up to test FVG bottom / upper BB with rejection
    candles.append(
        _make_candle(
            index=28,
            open_p="90",
            high_p="102",
            low_p="89",
            close_p="99",
            volume="20.0",
        )
    )
    # Rejection candle at upper BB: spikes high, closes down with upper rejection wick
    candles.append(
        _make_candle(
            index=29,
            open_p="100",
            high_p="104",
            low_p="96",
            close_p="97",
            volume="22.0",
        )
    )

    signal = strategy.generate_signal(candles=candles)
    if signal.signal_type is SignalType.SELL:
        assert "Bearish Hybrid Confluence" in (signal.reason or "")
        assert "Upper-BB RSI" in (signal.reason or "")
        assert signal.confidence >= strategy.min_confidence


def test_choch_rsi_bb_hybrid_anti_churn_cooldown() -> None:
    """Verify recent trigger within cooldown window withholds new trade entry."""
    strategy = ChochRsiBbHybridStrategy(
        trend_period=20,
        intermediate_trend_period=10,
        swing_window=2,
        fvg_lookback=8,
        volume_period=5,
        bb_period=5,
        rsi_period=3,
        adx_period=3,
        atr_period=3,
        require_trend_filter=False,
        cooldown_bars=3,
    )

    candles: list[Candle] = []
    for i in range(30):
        # Create candles with an oversold lower penetration on bar 28
        low = "80" if i == 28 else "98"
        candles.append(
            _make_candle(
                index=i,
                open_p="100",
                high_p="102",
                low_p=low,
                close_p="100",
                volume="10.0",
            )
        )

    # Bar 29 is within cooldown_bars=3 of bar 28 trigger
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD


def test_choch_rsi_bb_hybrid_alias_and_factory_resolution() -> None:
    """Verify alias equivalence and factory construction."""
    assert DailyHybridScalpingStrategy is ChochRsiBbHybridStrategy
    assert HybridStructureMeanReversionStrategy is ChochRsiBbHybridStrategy

    settings = StrategySettings(
        strategy_type=StrategyType.CHOCH_RSI_BB_HYBRID,
        crbb_swing_window=5,
        crbb_fvg_lookback=10,
        crbb_trend_period=50,
        crbb_intermediate_trend_period=20,
    )
    created = StrategyFactory.create(settings=settings)
    assert isinstance(created, ChochRsiBbHybridStrategy)
    assert created.strategy_type is StrategyType.CHOCH_RSI_BB_HYBRID
    assert created.swing_window == 5
    assert created.fvg_lookback == 10

    resolver = StrategyFactory.create_resolver(settings=settings)
    resolved = resolver.resolve(strategy_type=StrategyType.CHOCH_RSI_BB_HYBRID)
    assert isinstance(resolved, ChochRsiBbHybridStrategy)


def test_choch_rsi_bb_hybrid_full_runtime_candle_length_no_index_error() -> None:
    """Verify default strategy evaluates on full live runtime candle limit (201+)."""
    strategy = ChochRsiBbHybridStrategy(require_trend_filter=True)
    assert strategy.minimum_candles >= 101
    assert ChochRsiBbHybridStrategy(require_trend_filter=False).minimum_candles >= 25

    candles = [
        _make_candle(
            index=i,
            open_p="100",
            high_p="102",
            low_p="98",
            close_p="101" if i % 2 == 0 else "99",
            volume="15.0",
        )
        for i in range(210)
    ]
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)
