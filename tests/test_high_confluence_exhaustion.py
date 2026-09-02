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
    """Verify BUY signal when extreme oversold, lower BB, volume, and sweep align."""
    strategy = HighConfluenceExhaustionStrategy(trend_period=50)

    # 50 oscillating warmup candles
    closes = [Decimal(str(100.0 + (0.5 if i % 2 == 0 else -0.5))) for i in range(50)]
    # Consecutive drop with lower lows
    closes += [
        Decimal("97.0"),
        Decimal("97.5"),
        Decimal("94.0"),
        Decimal("94.5"),
        Decimal("91.0"),
        Decimal("91.5"),
        Decimal("87.0"),
        Decimal("83.0"),
        Decimal("78.5"),
    ]
    highs = [c + Decimal("0.8") for c in closes]
    lows = [c - Decimal("0.8") for c in closes]
    opens = [c for c in closes]

    # Reversal climax candle with long lower wick & sweep
    lows[-1] = Decimal("72.0")
    highs[-1] = Decimal("80.0")
    opens[-1] = Decimal("75.0")

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
    assert signal.confidence >= Decimal("0.70")
    assert signal.reason is not None
    assert "Long exhaustion confluence" in signal.reason


def test_high_confluence_exhaustion_generates_short_signal() -> None:
    """Verify SELL signal when extreme overbought, upper BB, volume, and sweep align."""
    strategy = HighConfluenceExhaustionStrategy(trend_period=50)

    # 50 oscillating warmup candles
    closes = [Decimal(str(100.0 + (0.5 if i % 2 == 0 else -0.5))) for i in range(50)]
    # Consecutive climb with higher highs
    closes += [
        Decimal("103.0"),
        Decimal("102.5"),
        Decimal("106.0"),
        Decimal("105.5"),
        Decimal("109.0"),
        Decimal("108.5"),
        Decimal("113.0"),
        Decimal("117.0"),
        Decimal("121.5"),
    ]
    highs = [c + Decimal("0.8") for c in closes]
    lows = [c - Decimal("0.8") for c in closes]
    opens = [c for c in closes]

    # Reversal climax candle with long upper wick & sweep
    lows[-1] = Decimal("120.0")
    highs[-1] = Decimal("128.0")
    opens[-1] = Decimal("125.0")

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
    assert signal.confidence >= Decimal("0.70")
    assert signal.reason is not None
    assert "Short exhaustion confluence" in signal.reason


def test_high_confluence_exhaustion_blocks_on_high_adx() -> None:
    """Verify HOLD signal when ADX exceeds runaway threshold."""
    strategy = HighConfluenceExhaustionStrategy(trend_period=50)

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
    strategy = HighConfluenceExhaustionStrategy(trend_period=50)
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
