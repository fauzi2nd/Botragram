"""
Botragram

Description:
    Unit tests for the HighConfluenceExhaustionStrategy.

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
from botragram.strategies.price_action import HighConfluenceExhaustionStrategy

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
def test_high_confluence_exhaustion_initialization_and_validation() -> None:
    """Verify parameters and bounded validation."""
    strategy = HighConfluenceExhaustionStrategy()
    assert strategy.strategy_type is StrategyType.HIGH_CONFLUENCE_EXHAUSTION
    assert strategy.minimum_candles >= 201

    with pytest.raises(ValueError, match="Bollinger Bands period"):
        HighConfluenceExhaustionStrategy(bb_period=0)

    with pytest.raises(ValueError, match="standard deviation"):
        HighConfluenceExhaustionStrategy(bb_std_dev=Decimal("0"))

    with pytest.raises(ValueError, match="RSI period"):
        HighConfluenceExhaustionStrategy(rsi_period=-1)

    with pytest.raises(ValueError, match="RSI thresholds"):
        HighConfluenceExhaustionStrategy(
            rsi_oversold=Decimal("80"), rsi_overbought=Decimal("20")
        )

    with pytest.raises(ValueError, match="Volume parameters"):
        HighConfluenceExhaustionStrategy(volume_multiplier=Decimal("-1"))

    with pytest.raises(ValueError, match="ADX parameters"):
        HighConfluenceExhaustionStrategy(adx_max_threshold=Decimal("0"))


def test_high_confluence_exhaustion_requires_minimum_candles() -> None:
    """Verify strategy fails closed if insufficient candle history is passed."""
    strategy = HighConfluenceExhaustionStrategy()
    short_candles = [
        _make_candle(
            index=i,
            open_p="100",
            high_p="101",
            low_p="99",
            close_p="100",
        )
        for i in range(50)
    ]
    with pytest.raises(ValueError, match="requires at least"):
        strategy.generate_signal(candles=short_candles)


def test_high_confluence_exhaustion_generates_long_signal() -> None:
    """Verify BUY signal when uptrend dip buying confluence aligns."""
    strategy = HighConfluenceExhaustionStrategy(
        trend_period=50, intermediate_trend_period=20, adx_max_threshold=Decimal("70.0")
    )

    # 40 candles rising, then 20 flat at 100, then 11 down candles
    closes = [Decimal(str(50.0 + i * 1.25)) for i in range(40)]
    closes += [Decimal("100.0") for _ in range(20)]
    closes += [Decimal(str(100.0 - (i + 1) * 0.7)) for i in range(11)]

    highs = [c + Decimal("0.8") for c in closes]
    lows = [c - Decimal("0.8") for c in closes]
    opens = [c for c in closes]

    # Climax candle with lower wick & sweep
    lows[-1] = Decimal("90.0")
    opens[-1] = Decimal("91.5")
    highs[-1] = Decimal("93.0")
    closes[-1] = Decimal("92.6")

    candles: list[Candle] = []
    for i in range(len(closes)):
        t = _START_TIME + timedelta(minutes=5 * i)
        vol = Decimal("35.0") if i == len(closes) - 1 else Decimal("10.0")
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M5,
                open_time=t,
                close_time=t + timedelta(minutes=5),
                open_price=opens[i],
                high_price=highs[i],
                low_price=lows[i],
                close_price=closes[i],
                volume=vol,
            )
        )

    signal = strategy.generate_signal(candles=candles)

    # Verify BUY signal was produced
    assert signal.signal_type is SignalType.BUY
    assert signal.confidence >= Decimal("0.65")
    assert signal.reason is not None
    assert "Long exhaustion confluence" in signal.reason


def test_high_confluence_exhaustion_generates_short_signal() -> None:
    """Verify SELL signal when downtrend rally exhaustion confluence aligns."""
    strategy = HighConfluenceExhaustionStrategy(
        trend_period=50, intermediate_trend_period=20, adx_max_threshold=Decimal("70.0")
    )

    # 40 candles falling, then 20 flat at 100, then 11 up candles
    closes = [Decimal(str(150.0 - i * 1.25)) for i in range(40)]
    closes += [Decimal("100.0") for _ in range(20)]
    closes += [Decimal(str(100.0 + (i + 1) * 0.7)) for i in range(11)]

    highs = [c + Decimal("0.8") for c in closes]
    lows = [c - Decimal("0.8") for c in closes]
    opens = [c for c in closes]

    # Climax candle with upper wick & sweep
    highs[-1] = Decimal("110.0")
    opens[-1] = Decimal("108.5")
    lows[-1] = Decimal("107.0")
    closes[-1] = Decimal("107.4")

    candles: list[Candle] = []
    for i in range(len(closes)):
        t = _START_TIME + timedelta(minutes=5 * i)
        vol = Decimal("35.0") if i == len(closes) - 1 else Decimal("10.0")
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M5,
                open_time=t,
                close_time=t + timedelta(minutes=5),
                open_price=opens[i],
                high_price=highs[i],
                low_price=lows[i],
                close_price=closes[i],
                volume=vol,
            )
        )

    signal = strategy.generate_signal(candles=candles)

    # Verify SELL signal was produced
    assert signal.signal_type is SignalType.SELL
    assert signal.confidence >= Decimal("0.65")
    assert signal.reason is not None
    assert "Short exhaustion confluence" in signal.reason


def test_high_confluence_exhaustion_blocks_on_high_adx() -> None:
    """Verify HOLD signal when ADX exceeds runaway threshold."""
    strategy = HighConfluenceExhaustionStrategy(
        trend_period=50, intermediate_trend_period=20
    )

    # Linear persistent plunge creates ADX > 40
    candles: list[Candle] = []
    for i in range(65):
        p = Decimal(str(150.0 - i * 0.8))
        t = _START_TIME + timedelta(minutes=5 * i)
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M5,
                open_time=t,
                close_time=t + timedelta(minutes=5),
                open_price=p + Decimal("0.5"),
                high_price=p + Decimal("1.0"),
                low_price=p - Decimal("1.0"),
                close_price=p,
                volume=Decimal("20.0"),
            )
        )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None
    assert "exceeds runaway threshold" in signal.reason


def test_high_confluence_exhaustion_blocks_on_insufficient_volume() -> None:
    """Verify HOLD signal when volume displacement is below multiplier."""
    strategy = HighConfluenceExhaustionStrategy(
        trend_period=50, intermediate_trend_period=20
    )
    candles: list[Candle] = []

    for i in range(65):
        candles.append(
            _make_candle(
                index=i,
                open_p="100.0",
                high_p="100.5",
                low_p="99.5",
                close_p="100.0",
                volume="10.0",
            )
        )

    # Final candle has normal volume (10.0, below 1.3x)
    candles.append(
        _make_candle(
            index=65,
            open_p="96.0",
            high_p="99.0",
            low_p="94.0",
            close_p="98.5",
            volume="10.0",
        )
    )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None
    assert "Insufficient volume" in signal.reason


def test_factory_creates_high_confluence_exhaustion_strategy() -> None:
    """Verify StrategyFactory creates and resolves HighConfluenceExhaustionStrategy."""
    settings = StrategySettings(strategy_type=StrategyType.HIGH_CONFLUENCE_EXHAUSTION)
    strategy = StrategyFactory.create(settings=settings)

    assert isinstance(strategy, HighConfluenceExhaustionStrategy)
    assert strategy.strategy_type is StrategyType.HIGH_CONFLUENCE_EXHAUSTION

    resolver = StrategyFactory.create_resolver(settings=settings)
    resolved = resolver.resolve(strategy_type=StrategyType.HIGH_CONFLUENCE_EXHAUSTION)
    assert isinstance(resolved, HighConfluenceExhaustionStrategy)


def test_high_confluence_exhaustion_strict_trend_blocks_counter_trend() -> None:
    """Verify falling knife below EMA is strictly rejected even with large wick."""
    strategy = HighConfluenceExhaustionStrategy(
        trend_period=50, intermediate_trend_period=20
    )

    # Warmup with high price (120) so EMA is high (~110+)
    closes = [Decimal("120.0") for _ in range(50)]
    # Steep drop so current price is well below EMA50
    closes += [
        Decimal("110.0"),
        Decimal("105.0"),
        Decimal("100.0"),
        Decimal("95.0"),
        Decimal("90.0"),
        Decimal("85.0"),
        Decimal("80.0"),
    ]
    highs = [c + Decimal("1.0") for c in closes]
    lows = [c - Decimal("1.0") for c in closes]
    opens = [c for c in closes]

    # Reversal candle with huge lower wick (53% wick ratio) but below EMA (~110)
    lows[-1] = Decimal("68.0")
    opens[-1] = Decimal("78.0")
    closes[-1] = Decimal("82.0")
    highs[-1] = Decimal("83.0")

    candles: list[Candle] = []
    for i in range(len(closes)):
        t = _START_TIME + timedelta(minutes=5 * i)
        vol = Decimal("40.0") if i == len(closes) - 1 else Decimal("10.0")
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M5,
                open_time=t,
                close_time=t + timedelta(minutes=5),
                open_price=opens[i],
                high_price=highs[i],
                low_price=lows[i],
                close_price=closes[i],
                volume=vol,
            )
        )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None
    assert "Exhaustion confluence conditions not met" in signal.reason


def test_high_confluence_exhaustion_blocks_on_low_confidence() -> None:
    """Verify HOLD signal when technical conditions pass but confidence < 0.75."""
    strategy = HighConfluenceExhaustionStrategy(
        trend_period=50,
        intermediate_trend_period=20,
        adx_max_threshold=Decimal("70.0"),
        volume_multiplier=Decimal("1.1"),
    )

    closes = [Decimal(str(50.0 + i * 1.25)) for i in range(40)]
    closes += [Decimal("100.0") for _ in range(20)]
    closes += [Decimal(str(100.0 - (i + 1) * 0.7)) for i in range(11)]

    highs = [c + Decimal("0.8") for c in closes]
    lows = [c - Decimal("0.8") for c in closes]
    opens = [c for c in closes]

    # Rejection candle meeting bare minimum (32% wick ratio, no sweep, no volume climax)
    # Range = 2.0. Lower wick = 0.65 -> 32.5% wick ratio (> 0.30 but < 0.40, no bonus)
    # Volume = 12.0 vs 10.0 SMA (1.2x >= 1.1x mult, but < 1.5x, no volume bonus)
    # Close is above EMA50 (~88)
    lows[-1] = Decimal("91.35")
    opens[-1] = Decimal("92.0")
    closes[-1] = Decimal("92.5")
    highs[-1] = Decimal("93.35")

    candles: list[Candle] = []
    for i in range(len(closes)):
        t = _START_TIME + timedelta(minutes=5 * i)
        vol = Decimal("12.0") if i == len(closes) - 1 else Decimal("10.0")
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M5,
                open_time=t,
                close_time=t + timedelta(minutes=5),
                open_price=opens[i],
                high_price=highs[i],
                low_price=lows[i],
                close_price=closes[i],
                volume=vol,
            )
        )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert signal.confidence < Decimal("0.75")
    assert signal.reason == "Confidence below threshold"


# =============================================================================
# Phase 6 — Macro Regime Filter Tests
# =============================================================================
def test_hce_regime_filter_blocks_long_in_bearish_regime() -> None:
    """Phase 6: LONG must be suppressed when EMA50 < EMA200 (bearish regime).

    Scenario: candle history is trending strongly down so EMA50 < EMA200.
    Despite an oversold bounce candle with all LONG confluence conditions met,
    the macro regime gate must emit HOLD and NOT BUY.
    """
    # trend_period=100, intermediate_trend_period=20
    # History: 80 candles falling sharply (150 -> 70) then 20 flat at low
    # => EMA20 ~= low price, EMA100 ~= much higher => bearish regime confirmed
    strategy = HighConfluenceExhaustionStrategy(
        trend_period=100,
        intermediate_trend_period=20,
        adx_max_threshold=Decimal("70.0"),
    )

    # 100 strongly descending candles: 150 down to 50, step -1 each
    closes = [Decimal(str(150 - i)) for i in range(100)]
    # Append a bounce reversal candle with lower wick + high volume
    bounced_close = Decimal("52.0")
    closes.append(bounced_close)

    highs = [c + Decimal("0.5") for c in closes]
    lows = [c - Decimal("0.5") for c in closes]
    opens = list(closes)

    # Make final candle a large lower-wick candle to satisfy LONG confluence
    lows[-1] = Decimal("42.0")  # huge lower wick (sweep below)
    opens[-1] = Decimal("50.0")
    closes[-1] = Decimal("52.0")
    highs[-1] = Decimal("53.0")

    candles: list[Candle] = []
    for i in range(len(closes)):
        t = _START_TIME + timedelta(minutes=5 * i)
        vol = Decimal("50.0") if i == len(closes) - 1 else Decimal("10.0")
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M5,
                open_time=t,
                close_time=t + timedelta(minutes=5),
                open_price=opens[i],
                high_price=highs[i],
                low_price=lows[i],
                close_price=closes[i],
                volume=vol,
            )
        )

    signal = strategy.generate_signal(candles=candles)
    # Regime filter blocks LONG; exhaustion conditions not met for SHORT either
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None


def test_hce_regime_filter_blocks_short_in_bullish_regime() -> None:
    """Phase 6: SHORT must be suppressed when EMA50 > EMA200 (bullish regime).

    Scenario: candle history is trending strongly up so EMA50 > EMA200.
    Despite an overbought rally candle with all SHORT confluence conditions met,
    the macro regime gate must emit HOLD (short blocked by uptrend regime).
    """
    strategy = HighConfluenceExhaustionStrategy(
        trend_period=100,
        intermediate_trend_period=20,
        adx_max_threshold=Decimal("200.0"),
    )

    # 100 strongly ascending candles: 50 up to 150, step +1 each
    closes = [Decimal(str(50 + i)) for i in range(100)]
    # Append a climax candle with upper wick to meet SHORT confluence
    closes.append(Decimal("148.0"))

    highs = [c + Decimal("0.5") for c in closes]
    lows = [c - Decimal("0.5") for c in closes]
    opens = list(closes)

    # Make final candle a large upper-wick candle (sweep above, rejection)
    highs[-1] = Decimal("158.0")
    opens[-1] = Decimal("150.0")
    closes[-1] = Decimal("148.0")
    lows[-1] = Decimal("147.0")

    candles: list[Candle] = []
    for i in range(len(closes)):
        t = _START_TIME + timedelta(minutes=5 * i)
        vol = Decimal("50.0") if i == len(closes) - 1 else Decimal("10.0")
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M5,
                open_time=t,
                close_time=t + timedelta(minutes=5),
                open_price=opens[i],
                high_price=highs[i],
                low_price=lows[i],
                close_price=closes[i],
                volume=vol,
            )
        )

    signal = strategy.generate_signal(candles=candles)
    # Regime is bullish: SHORT blocked → "Short blocked by macro uptrend regime"
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None
    assert "Short blocked by macro uptrend regime" in signal.reason


def test_hce_rejects_invalid_intermediate_trend_period() -> None:
    """Phase 6: intermediate_trend_period must be < trend_period."""
    with pytest.raises(ValueError, match="intermediate_trend_period must be less"):
        HighConfluenceExhaustionStrategy(trend_period=50, intermediate_trend_period=50)

    with pytest.raises(ValueError, match="intermediate_trend_period must be less"):
        HighConfluenceExhaustionStrategy(trend_period=50, intermediate_trend_period=100)

    with pytest.raises(ValueError, match="Intermediate trend period must be positive"):
        HighConfluenceExhaustionStrategy(trend_period=200, intermediate_trend_period=0)
