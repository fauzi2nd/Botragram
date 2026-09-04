"""
Botragram

Description:
    Unit tests for LiquiditySweepExhaustionStrategy (LSE).

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
from botragram.strategies.price_action import LiquiditySweepExhaustionStrategy

# =============================================================================
# Constants
# =============================================================================
_START_TIME = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def _make_candle(
    *,
    index: int,
    open_p: str,
    high_p: str,
    low_p: str,
    close_p: str,
    volume: str = "10.0",
    start_time: datetime = _START_TIME,
    symbol: str = "BTCUSDT",
) -> Candle:
    open_time = start_time + timedelta(minutes=5 * index)
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
def test_lse_initialization_and_validation() -> None:
    """Verify parameters and bounded validation."""
    strategy = LiquiditySweepExhaustionStrategy()
    assert strategy.strategy_type is StrategyType.LIQUIDITY_SWEEP_EXHAUSTION
    assert strategy.minimum_candles >= 18

    with pytest.raises(ValueError, match="Swing lookback"):
        LiquiditySweepExhaustionStrategy(swing_lookback=0)

    with pytest.raises(ValueError, match="Minimum wick ratio"):
        LiquiditySweepExhaustionStrategy(min_wick_ratio=Decimal("0"))

    with pytest.raises(ValueError, match="Volume parameters"):
        LiquiditySweepExhaustionStrategy(volume_period=0)

    with pytest.raises(ValueError, match="Volume parameters"):
        LiquiditySweepExhaustionStrategy(volume_multiplier=Decimal("0"))

    with pytest.raises(ValueError, match="RSI period"):
        LiquiditySweepExhaustionStrategy(rsi_period=0)

    with pytest.raises(ValueError, match="RSI oversold/overbought"):
        LiquiditySweepExhaustionStrategy(
            rsi_oversold=Decimal("70.0"), rsi_overbought=Decimal("30.0")
        )

    with pytest.raises(ValueError, match="ATR period"):
        LiquiditySweepExhaustionStrategy(atr_period=0)

    with pytest.raises(ValueError, match="ATR multipliers"):
        LiquiditySweepExhaustionStrategy(atr_multiplier_sl=Decimal("0"))

    with pytest.raises(ValueError, match="NATR thresholds"):
        LiquiditySweepExhaustionStrategy(
            min_natr_threshold=Decimal("0.05"), max_natr_threshold=Decimal("0.01")
        )

    with pytest.raises(ValueError, match="Funding buffer minutes"):
        LiquiditySweepExhaustionStrategy(funding_buffer_minutes=-1)

    with pytest.raises(ValueError, match="Minimum confidence"):
        LiquiditySweepExhaustionStrategy(min_confidence=Decimal("1.5"))

    with pytest.raises(ValueError, match="Cooldown bars"):
        LiquiditySweepExhaustionStrategy(cooldown_bars=-1)

    with pytest.raises(ValueError, match="Maximum hold bars"):
        LiquiditySweepExhaustionStrategy(max_hold_bars=0)

    with pytest.raises(ValueError, match="Short bias multiplier"):
        LiquiditySweepExhaustionStrategy(short_bias_multiplier=Decimal("0.5"))


def test_lse_minimum_candles_validation() -> None:
    """Verify ValueError is raised when insufficient candles are supplied."""
    strategy = LiquiditySweepExhaustionStrategy(swing_lookback=10)
    candles = [
        _make_candle(index=i, open_p="100", high_p="102", low_p="98", close_p="100")
        for i in range(5)
    ]
    with pytest.raises(ValueError, match="requires at least"):
        strategy.generate_signal(candles=candles)


def test_lse_funding_settlement_window_hold() -> None:
    """Verify entry is withheld during funding settlement window."""
    strategy = LiquiditySweepExhaustionStrategy(
        filter_funding=True,
        funding_buffer_minutes=15,
        swing_lookback=5,
        volume_period=5,
        rsi_period=5,
        atr_period=5,
        min_natr_threshold=Decimal("0.0001"),
    )
    # Candle 24 close time at 08:10 UTC (inside 08:00 - 08:15 funding window)
    funding_time = datetime(2026, 1, 1, 6, 5, tzinfo=timezone.utc)
    candles = [
        _make_candle(
            index=i,
            open_p="100",
            high_p="105",
            low_p="95",
            close_p="101" if i % 2 == 0 else "99",
            start_time=funding_time,
        )
        for i in range(25)
    ]
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "Funding settlement window" in (signal.reason or "")


def test_lse_volatility_filters() -> None:
    """Verify flat market and volatility shock guards."""
    # 1. Volatility too low (flat market)
    strategy_low = LiquiditySweepExhaustionStrategy(
        swing_lookback=5,
        volume_period=5,
        rsi_period=5,
        atr_period=5,
        min_natr_threshold=Decimal("0.05"),
        max_natr_threshold=Decimal("0.10"),
        filter_funding=False,
    )
    candles_flat = [
        _make_candle(
            index=i,
            open_p="100.00",
            high_p="100.01",
            low_p="99.99",
            close_p="100.00",
        )
        for i in range(25)
    ]
    sig_flat = strategy_low.generate_signal(candles=candles_flat)
    assert sig_flat.signal_type is SignalType.HOLD
    assert "Volatility too low" in (sig_flat.reason or "")

    # 2. Volatility shock (extreme NATR)
    strategy_shock = LiquiditySweepExhaustionStrategy(
        swing_lookback=5,
        volume_period=5,
        rsi_period=5,
        atr_period=5,
        min_natr_threshold=Decimal("0.0001"),
        max_natr_threshold=Decimal("0.02"),
        filter_funding=False,
    )
    candles_shock = [
        _make_candle(
            index=i,
            open_p="100",
            high_p="130",
            low_p="70",
            close_p="105" if i % 2 == 0 else "95",
        )
        for i in range(25)
    ]
    sig_shock = strategy_shock.generate_signal(candles=candles_shock)
    assert sig_shock.signal_type is SignalType.HOLD
    assert "Extreme volatility shock" in (sig_shock.reason or "")


def test_lse_bullish_liquidity_sweep_generation() -> None:
    """Verify Bullish Liquidity Sweep triggers BUY with dynamic SL/TP."""
    strategy = LiquiditySweepExhaustionStrategy(
        swing_lookback=8,
        volume_period=10,
        rsi_period=10,
        atr_period=10,
        min_wick_ratio=Decimal("0.50"),
        volume_multiplier=Decimal("1.30"),
        rsi_oversold=Decimal("40.0"),
        min_natr_threshold=Decimal("0.0001"),
        max_natr_threshold=Decimal("0.08"),
        filter_funding=False,
        min_confidence=Decimal("0.60"),
        cooldown_bars=0,
    )

    candles: list[Candle] = []
    # 0..14: Baseline range around 105
    for i in range(15):
        candles.append(
            _make_candle(
                index=i,
                open_p="105",
                high_p="107",
                low_p="103",
                close_p="105",
                volume="10.0",
            )
        )

    # 15..24: Downtrend leading to oversold RSI
    for i in range(15, 25):
        price = str(103 - (i - 15))
        candles.append(
            _make_candle(
                index=i,
                open_p=str(int(price) + 1),
                high_p=str(int(price) + 2),
                low_p=str(int(price) - 1),
                close_p=price,
                volume="10.0",
            )
        )

    # 25: Sweep candle (T-1)
    # Low = 85.0 (< prior swing low of 93.0)
    # High = 95.0, Open = 94.0, Close = 92.0 -> lower body edge = 92.0
    # Lower wick = 92.0 - 85.0 = 7.0 (70% of range 10.0)
    # Volume = 25.0 (> 1.3x)
    # Midpoint = (95.0 + 85.0) / 2 = 90.0
    candles.append(
        _make_candle(
            index=25,
            open_p="94.0",
            high_p="95.0",
            low_p="85.0",
            close_p="92.0",
            volume="25.0",
        )
    )

    # 26: Confirmation candle (T)
    # Closes at 94.0 > midpoint 90.0
    candles.append(
        _make_candle(
            index=26,
            open_p="92.0",
            high_p="96.0",
            low_p="91.0",
            close_p="94.0",
            volume="12.0",
        )
    )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert signal.confidence >= Decimal("0.60")
    assert "Bullish Liquidity Sweep" in (signal.reason or "")
    assert "Low sweep" in (signal.reason or "")
    assert "TP1" in (signal.reason or "")
    assert "TP2" in (signal.reason or "")


def test_lse_bearish_liquidity_sweep_generation() -> None:
    """Verify Bearish Liquidity Sweep triggers SELL with asymmetric boost."""
    strategy = LiquiditySweepExhaustionStrategy(
        swing_lookback=8,
        volume_period=10,
        rsi_period=10,
        atr_period=10,
        min_wick_ratio=Decimal("0.50"),
        volume_multiplier=Decimal("1.30"),
        rsi_overbought=Decimal("60.0"),
        min_natr_threshold=Decimal("0.0001"),
        max_natr_threshold=Decimal("0.08"),
        filter_funding=False,
        min_confidence=Decimal("0.60"),
        cooldown_bars=0,
    )

    candles: list[Candle] = []
    # 0..14: Baseline range around 95
    for i in range(15):
        candles.append(
            _make_candle(
                index=i,
                open_p="95",
                high_p="97",
                low_p="93",
                close_p="95",
                volume="10.0",
            )
        )

    # 15..24: Uptrend leading to overbought RSI
    for i in range(15, 25):
        price = str(97 + (i - 15))
        candles.append(
            _make_candle(
                index=i,
                open_p=str(int(price) - 1),
                high_p=str(int(price) + 1),
                low_p=str(int(price) - 2),
                close_p=price,
                volume="10.0",
            )
        )

    # 25: Sweep candle (T-1)
    # High = 116.0 (> prior swing high of 107.0)
    # Low = 105.0, Open = 106.0, Close = 108.0 -> upper body edge = 108.0
    # Upper wick = 116.0 - 108.0 = 8.0 (72% of range 11.0)
    # Volume = 25.0
    # Midpoint = (116.0 + 105.0) / 2 = 110.5
    candles.append(
        _make_candle(
            index=25,
            open_p="106.0",
            high_p="116.0",
            low_p="105.0",
            close_p="108.0",
            volume="25.0",
        )
    )

    # 26: Confirmation candle (T)
    # Closes at 106.0 < midpoint 110.5
    candles.append(
        _make_candle(
            index=26,
            open_p="108.0",
            high_p="109.0",
            low_p="105.0",
            close_p="106.0",
            volume="12.0",
        )
    )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.SELL
    assert signal.confidence >= Decimal("0.60")
    assert "Bearish Liquidity Sweep" in (signal.reason or "")
    assert "High sweep" in (signal.reason or "")


def test_lse_wick_ratio_filter_rejection() -> None:
    """Verify rejection when sweep candle wick is less than 50%."""
    strategy = LiquiditySweepExhaustionStrategy(
        swing_lookback=5,
        volume_period=5,
        rsi_period=5,
        atr_period=5,
        min_wick_ratio=Decimal("0.50"),
        min_natr_threshold=Decimal("0.0001"),
        filter_funding=False,
        cooldown_bars=0,
    )
    candles = [
        _make_candle(index=i, open_p="100", high_p="102", low_p="98", close_p="100")
        for i in range(20)
    ]
    # Candle with only 20% lower wick
    candles.append(
        _make_candle(
            index=20,
            open_p="98.0",
            high_p="100.0",
            low_p="95.0",
            close_p="96.0",
            volume="25.0",
        )
    )
    candles.append(
        _make_candle(
            index=21,
            open_p="96.0",
            high_p="99.0",
            low_p="96.0",
            close_p="98.0",
            volume="10.0",
        )
    )
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD


def test_lse_cooldown_rejection() -> None:
    """Verify consecutive triggers within cooldown bars are suppressed."""
    strategy = LiquiditySweepExhaustionStrategy(
        swing_lookback=5,
        volume_period=5,
        rsi_period=5,
        atr_period=5,
        min_natr_threshold=Decimal("0.0001"),
        filter_funding=False,
        cooldown_bars=2,
    )
    candles = [
        _make_candle(index=i, open_p="100", high_p="105", low_p="95", close_p="100")
        for i in range(20)
    ]
    # Bar 19 was a high-wick rejection
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD


def test_lse_factory_and_resolver() -> None:
    """Verify factory construction and resolver for LIQUIDITY_SWEEP_EXHAUSTION."""
    settings = StrategySettings(
        strategy_type=StrategyType.LIQUIDITY_SWEEP_EXHAUSTION,
        lse_swing_lookback=12,
        lse_min_wick_ratio=Decimal("0.55"),
        lse_volume_multiplier=Decimal("1.35"),
        lse_rsi_oversold=Decimal("35.0"),
    )
    strategy = StrategyFactory.create(settings=settings)
    assert isinstance(strategy, LiquiditySweepExhaustionStrategy)
    assert strategy.strategy_type is StrategyType.LIQUIDITY_SWEEP_EXHAUSTION
    assert strategy.swing_lookback == 12
    assert strategy.min_wick_ratio == Decimal("0.55")

    resolver = StrategyFactory.create_resolver(settings=settings)
    resolved = resolver.resolve(strategy_type=StrategyType.LIQUIDITY_SWEEP_EXHAUSTION)
    assert isinstance(resolved, LiquiditySweepExhaustionStrategy)
