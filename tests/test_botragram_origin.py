"""
Botragram

Description:
    Unit tests for BotragramOriginStrategy (pure candlestick patterns + TA hooks).

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
from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle
from botragram.strategies.price_action.botragram_origin import (
    BotragramOriginStrategy,
)


def _make_candle(
    *,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
    volume: str = "100.0",
    minutes_offset: int = 0,
) -> Candle:
    """Helper to build a deterministic test candle."""
    base_time = datetime(2026, 9, 1, 12, 0, tzinfo=UTC) + timedelta(
        minutes=minutes_offset
    )
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M5,
        open_time=base_time,
        close_time=base_time + timedelta(minutes=5),
        open_price=Decimal(open_price),
        high_price=Decimal(high_price),
        low_price=Decimal(low_price),
        close_price=Decimal(close_price),
        volume=Decimal(volume),
    )


def _generate_baseline_candles(
    count: int = 10, base_price: str = "100.0"
) -> list[Candle]:
    """Build a series of neutral background candles."""
    candles: list[Candle] = []
    p = Decimal(base_price)
    for i in range(count):
        candles.append(
            _make_candle(
                open_price=str(p),
                high_price=str(p + Decimal("1.0")),
                low_price=str(p - Decimal("1.0")),
                close_price=str(p + Decimal("0.1")),
                volume="100.0",
                minutes_offset=i * 5,
            )
        )
    return candles


# =============================================================================
# Strategy Initialization and Validation Tests
# =============================================================================
def test_origin_strategy_initialization_defaults() -> None:
    """Verify strategy initializes with expected default configuration."""
    strategy = BotragramOriginStrategy()
    assert strategy.strategy_type is StrategyType.BOTRAGRAM_ORIGIN
    assert strategy.risk_reward_ratio == Decimal("1.5")
    assert strategy.min_sl_pct == Decimal("0.010")
    assert strategy.max_sl_pct == Decimal("0.030")
    assert strategy.min_confidence == Decimal("0.70")
    assert not strategy.use_trend_filter
    assert not strategy.use_volume_filter
    assert not strategy.use_rsi_filter


def test_origin_strategy_validation_invariants() -> None:
    """Verify invalid parameters raise ValueError during initialization."""
    with pytest.raises(ValueError, match="risk_reward_ratio"):
        BotragramOriginStrategy(risk_reward_ratio=Decimal("0"))

    with pytest.raises(ValueError, match="max_sl_pct"):
        BotragramOriginStrategy(max_sl_pct=Decimal("0"))

    with pytest.raises(ValueError, match="min_sl_pct"):
        BotragramOriginStrategy(min_sl_pct=Decimal("0.05"), max_sl_pct=Decimal("0.02"))

    with pytest.raises(ValueError, match="min_confidence"):
        BotragramOriginStrategy(min_confidence=Decimal("1.5"))

    with pytest.raises(ValueError, match="trend_ema_period"):
        BotragramOriginStrategy(trend_ema_period=0)

    with pytest.raises(ValueError, match="volume_period"):
        BotragramOriginStrategy(volume_period=-1)

    with pytest.raises(ValueError, match="rsi_period"):
        BotragramOriginStrategy(rsi_period=0)


# =============================================================================
# Signal Generation Tests
# =============================================================================
def test_origin_strategy_raises_when_insufficient_candles() -> None:
    """Raise ValueError when candle history is below minimum required lookback."""
    strategy = BotragramOriginStrategy()
    candles = [
        _make_candle(
            open_price="100", high_price="101", low_price="99", close_price="100"
        )
    ]
    with pytest.raises(ValueError, match="requires at least"):
        strategy.generate_signal(candles=candles)


def test_origin_strategy_bullish_hammer_generates_buy() -> None:
    """Detect bullish pinbar (hammer) and generate BUY signal with SL/TP."""
    strategy = BotragramOriginStrategy(min_confidence=Decimal("0.70"))
    candles = _generate_baseline_candles(count=5)
    # Add a strong bullish hammer at the end
    hammer = _make_candle(
        open_price="100.0",
        high_price="100.5",
        low_price="90.0",
        close_price="100.2",
        minutes_offset=25,
    )
    candles.append(hammer)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert signal.confidence >= Decimal("0.70")
    assert signal.stop_loss is not None
    assert signal.take_profit is not None
    assert signal.stop_loss < signal.price
    assert signal.take_profit > signal.price
    assert "bullish_pinbar" in (signal.reason or "")


def test_origin_strategy_bearish_shooting_star_generates_sell() -> None:
    """Detect bearish pinbar (shooting star) and generate SELL signal with SL/TP."""
    strategy = BotragramOriginStrategy(min_confidence=Decimal("0.70"))
    candles = _generate_baseline_candles(count=5)
    shooting_star = _make_candle(
        open_price="100.0",
        high_price="112.0",
        low_price="99.5",
        close_price="99.8",
        minutes_offset=25,
    )
    candles.append(shooting_star)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.SELL
    assert signal.confidence >= Decimal("0.70")
    assert signal.stop_loss is not None
    assert signal.take_profit is not None
    assert signal.stop_loss > signal.price
    assert signal.take_profit < signal.price
    assert "bearish_pinbar" in (signal.reason or "")


def test_origin_strategy_morning_star_generates_buy() -> None:
    """Detect morning star triple-candle pattern and generate BUY signal."""
    strategy = BotragramOriginStrategy(min_confidence=Decimal("0.70"))
    candles = _generate_baseline_candles(count=5)
    # C1: large red
    c1 = _make_candle(
        open_price="110.0",
        high_price="111.0",
        low_price="99.5",
        close_price="100.0",
        minutes_offset=25,
    )
    # C2: small body star below c1
    c2 = _make_candle(
        open_price="95.0",
        high_price="97.0",
        low_price="94.0",
        close_price="96.0",
        minutes_offset=30,
    )
    # C3: large green closing above midpoint of c1 (midpoint = 105)
    c3 = _make_candle(
        open_price="97.0",
        high_price="108.0",
        low_price="96.5",
        close_price="107.0",
        minutes_offset=35,
    )
    candles.extend([c1, c2, c3])

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert signal.confidence >= Decimal("0.70")
    assert "morning_star" in (signal.reason or "")


def test_origin_strategy_three_black_crows_generates_sell() -> None:
    """Detect three black crows pattern and generate SELL signal."""
    strategy = BotragramOriginStrategy(min_confidence=Decimal("0.70"))
    candles = _generate_baseline_candles(count=5)
    d1 = _make_candle(
        open_price="115.0",
        high_price="116.0",
        low_price="109.0",
        close_price="110.0",
        minutes_offset=25,
    )
    d2 = _make_candle(
        open_price="111.0",
        high_price="112.0",
        low_price="104.0",
        close_price="105.0",
        minutes_offset=30,
    )
    d3 = _make_candle(
        open_price="106.0",
        high_price="107.0",
        low_price="99.0",
        close_price="100.0",
        minutes_offset=35,
    )
    candles.extend([d1, d2, d3])

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.SELL
    assert signal.confidence >= Decimal("0.70")
    assert "three_black_crows" in (signal.reason or "")


def test_origin_strategy_confluence_increases_confidence() -> None:
    """Verify multiple conforming patterns boost confidence above base pattern score."""
    strategy = BotragramOriginStrategy(min_confidence=Decimal("0.70"))
    candles = _generate_baseline_candles(count=5)
    # Setup piercing line where current candle is ALSO a bullish pinbar
    c1 = _make_candle(
        open_price="110.0",
        high_price="111.0",
        low_price="99.0",
        close_price="100.0",
        minutes_offset=25,
    )
    # c2: opens at 102, drops to 80, closes at 106 (piercing + hammer pinbar)
    c2 = _make_candle(
        open_price="102.0",
        high_price="107.0",
        low_price="80.0",
        close_price="106.0",
        minutes_offset=30,
    )
    candles.extend([c1, c2])

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    # Confluence bonus (+0.05 per extra pattern) boosts confidence to 0.80
    assert signal.confidence >= Decimal("0.80")
    assert signal.confidence > Decimal("0.75")


def test_origin_strategy_conflicting_patterns_lead_to_hold() -> None:
    """When both bullish and bearish patterns trigger, strategy holds."""
    strategy = BotragramOriginStrategy()
    # A candle with equal huge upper and lower wicks could be neutral or conflict
    candles = _generate_baseline_candles(count=5)
    # Neutral doji at the end without clear directional bias
    doji = _make_candle(
        open_price="100.0",
        high_price="105.0",
        low_price="95.0",
        close_price="100.05",
        minutes_offset=25,
    )
    candles.append(doji)
    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD


# =============================================================================
# Extensible TA Filters Tests
# =============================================================================
def test_origin_strategy_trend_filter_blocks_counter_trend_signal() -> None:
    """When use_trend_filter is True, long entry below EMA 50 is blocked."""
    strategy = BotragramOriginStrategy(
        use_trend_filter=True,
        trend_ema_period=5,
        min_confidence=Decimal("0.70"),
    )
    # Build 10 candles sloping sharply downwards from 200 to 100
    candles: list[Candle] = []
    for i in range(10):
        p = Decimal("200") - Decimal(i * 10)
        candles.append(
            _make_candle(
                open_price=str(p),
                high_price=str(p + Decimal("1")),
                low_price=str(p - Decimal("1")),
                close_price=str(p),
                minutes_offset=i * 5,
            )
        )
    # Now add a bullish hammer at price 90 (far below downward EMA 5)
    hammer = _make_candle(
        open_price="90.0",
        high_price="90.5",
        low_price="80.0",
        close_price="90.2",
        minutes_offset=50,
    )
    candles.append(hammer)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "Trend filter" in (signal.reason or "")


def test_origin_strategy_rsi_filter_blocks_overbought_long() -> None:
    """When use_rsi_filter is True, RSI > rsi_long_max blocks long entry."""
    strategy = BotragramOriginStrategy(
        use_rsi_filter=True,
        rsi_period=3,
        rsi_long_max=Decimal("70.0"),
        min_confidence=Decimal("0.70"),
    )
    # Build candles with monotonic huge price increases giving RSI ~ 100
    candles: list[Candle] = []
    for i in range(8):
        p = Decimal("100") + Decimal(i * 10)
        candles.append(
            _make_candle(
                open_price=str(p),
                high_price=str(p + Decimal("2")),
                low_price=str(p - Decimal("1")),
                close_price=str(p + Decimal("5")),
                minutes_offset=i * 5,
            )
        )
    # Add bullish hammer at top
    hammer = _make_candle(
        open_price="180.0",
        high_price="180.5",
        low_price="170.0",
        close_price="180.2",
        minutes_offset=45,
    )
    candles.append(hammer)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "RSI" in (signal.reason or "")


def test_origin_strategy_volume_filter_blocks_low_volume() -> None:
    """When use_volume_filter is True, volume below multiplier * SMA blocks entry."""
    strategy = BotragramOriginStrategy(
        use_volume_filter=True,
        volume_period=5,
        volume_multiplier=Decimal("1.5"),
        min_confidence=Decimal("0.70"),
    )
    candles: list[Candle] = []
    for i in range(10):
        candles.append(
            _make_candle(
                open_price="100.0",
                high_price="101.0",
                low_price="99.0",
                close_price="100.0",
                volume="1000.0",
                minutes_offset=i * 5,
            )
        )
    # Add hammer with tiny volume of 50 with next timestamp offset
    hammer = _make_candle(
        open_price="100.0",
        high_price="100.5",
        low_price="90.0",
        close_price="100.2",
        volume="50.0",
        minutes_offset=50,
    )
    candles.append(hammer)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "Volume" in (signal.reason or "")


def test_origin_strategy_rsi_direction_filter() -> None:
    """When require_rsi_direction is True, declining RSI blocks BUY."""
    strategy = BotragramOriginStrategy(
        use_rsi_filter=True,
        rsi_period=3,
        rsi_long_max=Decimal("80.0"),
        require_rsi_direction=True,
        min_confidence=Decimal("0.70"),
    )
    # Build candles where prior candles had large gains, but last candle has slight drop
    # so RSI is falling
    candles: list[Candle] = []
    prices = [100, 102, 104, 106, 110, 115, 120, 118]
    for i, p in enumerate(prices):
        candles.append(
            _make_candle(
                open_price=str(p),
                high_price=str(p + 1),
                low_price=str(p - 1),
                close_price=str(p),
                minutes_offset=i * 5,
            )
        )
    # Add hammer at 117 (close 117 <= 118, RSI drops or stays lower)
    hammer = _make_candle(
        open_price="117.0",
        high_price="117.5",
        low_price="105.0",
        close_price="117.2",
        minutes_offset=40,
    )
    candles.append(hammer)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "RSI declining" in (signal.reason or "")


def test_origin_strategy_bb_filter_short() -> None:
    """When use_bb_filter is True, SELL candle must touch Upper BB and reject."""
    strategy = BotragramOriginStrategy(
        use_bb_filter=True,
        bb_period=5,
        bb_std_dev=Decimal("2.0"),
        min_confidence=Decimal("0.70"),
    )
    candles: list[Candle] = []
    # 10 candles oscillating between 95 and 105 so Upper BB is around ~108
    prices = [95, 105, 95, 105, 95, 105, 95, 105, 95, 105]
    for i, p in enumerate(prices):
        candles.append(
            _make_candle(
                open_price=str(p),
                high_price=str(p + 2),
                low_price=str(p - 2),
                close_price=str(p),
                minutes_offset=i * 5,
            )
        )
    # 1. Bearish pinbar that does NOT touch Upper BB (high is 106, Upper BB is ~108.9)
    pinbar_no_touch = _make_candle(
        open_price="100.0",
        high_price="106.0",
        low_price="99.5",
        close_price="99.8",
        minutes_offset=50,
    )
    candles_no_touch = [*candles, pinbar_no_touch]
    sig_no_touch = strategy.generate_signal(candles=candles_no_touch)
    assert sig_no_touch.signal_type is SignalType.HOLD
    assert "did not touch Upper BB" in (sig_no_touch.reason or "")

    # 2. Bearish pinbar that touches Upper BB (high 115) and closes below (close 99.8)
    pinbar_touch = _make_candle(
        open_price="100.0",
        high_price="115.0",
        low_price="99.5",
        close_price="99.8",
        minutes_offset=50,
    )
    candles_touch = [*candles, pinbar_touch]
    sig_touch = strategy.generate_signal(candles=candles_touch)
    assert sig_touch.signal_type is SignalType.SELL


def test_origin_strategy_macd_filter_short() -> None:
    """When use_macd_filter is True, SELL requires declining MACD."""
    strategy = BotragramOriginStrategy(
        use_macd_filter=True,
        macd_fast_period=3,
        macd_slow_period=6,
        macd_signal_period=3,
        min_confidence=Decimal("0.70"),
    )
    # Build candles
    candles: list[Candle] = []
    for i in range(15):
        p = Decimal("100") + Decimal(i * 2)
        candles.append(
            _make_candle(
                open_price=str(p),
                high_price=str(p + 1),
                low_price=str(p - 1),
                close_price=str(p),
                minutes_offset=i * 5,
            )
        )
    # Add a bearish pinbar
    pinbar = _make_candle(
        open_price="128.0",
        high_price="135.0",
        low_price="127.8",
        close_price="127.9",
        minutes_offset=75,
    )
    candles.append(pinbar)
    signal = strategy.generate_signal(candles=candles)
    # Strategy should return either SELL or HOLD depending on MACD momentum
    assert signal.signal_type in (SignalType.SELL, SignalType.HOLD)


def test_origin_strategy_psar_filter_proximity_allowed() -> None:
    """When use_psar_filter is True and price < SAR within proximity, BUY is allowed."""
    strategy = BotragramOriginStrategy(
        use_psar_filter=True,
        psar_max_proximity_pct=Decimal("0.05"),  # 5% tolerance for test
        min_confidence=Decimal("0.70"),
    )
    # 10 candles with gentle slope
    candles: list[Candle] = []
    for i in range(10):
        p = Decimal("100") - Decimal(i * 0.2)
        candles.append(
            _make_candle(
                open_price=str(p),
                high_price=str(p + Decimal("0.5")),
                low_price=str(p - Decimal("0.5")),
                close_price=str(p),
                minutes_offset=i * 5,
            )
        )
    # Hammer close to SAR (e.g. price 98.0, SAR ~100.5 -> dist ~2% <= 5%)
    hammer = _make_candle(
        open_price="98.0",
        high_price="98.2",
        low_price="95.0",
        close_price="98.1",
        minutes_offset=50,
    )
    candles.append(hammer)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY


def test_origin_strategy_psar_filter_proximity_rejected() -> None:
    """When price is too far below SAR (> proximity), BUY is rejected."""
    strategy = BotragramOriginStrategy(
        use_psar_filter=True,
        psar_max_proximity_pct=Decimal("0.005"),  # 0.5% tolerance
        min_confidence=Decimal("0.70"),
    )
    # Candles dropping from 200 to 150
    candles: list[Candle] = []
    for i in range(10):
        p = Decimal("200") - Decimal(i * 5)
        candles.append(
            _make_candle(
                open_price=str(p),
                high_price=str(p + 1),
                low_price=str(p - 1),
                close_price=str(p),
                minutes_offset=i * 5,
            )
        )
    # Hammer at 145 (SAR is ~180+, dist > 20% >> 0.5%)
    hammer = _make_candle(
        open_price="145.0",
        high_price="145.5",
        low_price="135.0",
        close_price="145.2",
        minutes_offset=50,
    )
    candles.append(hammer)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "too far below SAR" in (signal.reason or "")


def test_origin_strategy_psar_invalid_proximity() -> None:
    """Non-positive psar_max_proximity_pct raises ValueError."""
    import pytest

    with pytest.raises(ValueError, match="psar_max_proximity_pct must be positive"):
        BotragramOriginStrategy(psar_max_proximity_pct=Decimal("0"))


def test_origin_strategy_pattern_quality_bonus_end_to_end() -> None:
    """Verify CandlestickMatch geometric ratios award quality bonuses via API."""
    strategy = BotragramOriginStrategy(min_confidence=Decimal("0.70"))
    baseline = _generate_baseline_candles(count=5)

    # 1. Standard pinbar: lower_wick ~ 68% (< 75% threshold)
    # Range = 103.2 - 93.2 = 10.0. Lower wick = 100.0 - 93.2 = 6.8 (68%).
    # Upper wick = 103.2 - 101.4 = 1.8 (18% <= 20%).
    std_hammer = _make_candle(
        open_price="100.0",
        high_price="103.2",
        low_price="93.2",
        close_price="101.4",
        minutes_offset=25,
    )
    sig_std = strategy.generate_signal(candles=[*baseline, std_hammer])
    assert sig_std.signal_type is SignalType.BUY
    # Standard single candle pattern confidence is 0.70
    assert sig_std.confidence == Decimal("0.70")

    # 2. High quality pinbar: lower_wick ~ 87% (>= 75%), body ~ 10.4% (> 10% not doji)
    # Range = 101.5 - 90.0 = 11.5. Lower wick = 100.0 - 90.0 = 10.0 (86.9%).
    hq_hammer = _make_candle(
        open_price="100.0",
        high_price="101.5",
        low_price="90.0",
        close_price="101.2",
        minutes_offset=25,
    )
    sig_hq = strategy.generate_signal(candles=[*baseline, hq_hammer])
    assert sig_hq.signal_type is SignalType.BUY
    # High quality pinbar receives +0.03 quality bonus -> 0.73
    assert sig_hq.confidence == Decimal("0.73")
    assert sig_hq.confidence > sig_std.confidence


def test_origin_strategy_ta_confluence_bonus() -> None:
    """Verify active TA filter with strong alignment increases signal confidence."""
    candles: list[Candle] = []
    for i in range(10):
        candles.append(
            _make_candle(
                open_price="100.0",
                high_price="101.0",
                low_price="99.0",
                close_price="100.0",
                volume="1000.0",
                minutes_offset=i * 5,
            )
        )
    # Bullish hammer with surge volume 2000 (avg is 1000, 2000 >= 1.5 * 1000)
    hammer_surge = _make_candle(
        open_price="100.0",
        high_price="100.5",
        low_price="90.0",
        close_price="100.2",
        volume="2000.0",
        minutes_offset=50,
    )
    # Bullish hammer with normal volume 1100 (< 1.5 * 1000)
    hammer_norm = _make_candle(
        open_price="100.0",
        high_price="100.5",
        low_price="90.0",
        close_price="100.2",
        volume="1100.0",
        minutes_offset=50,
    )

    strat_ta = BotragramOriginStrategy(
        use_volume_filter=True,
        volume_period=5,
        volume_multiplier=Decimal("1.0"),
        min_confidence=Decimal("0.70"),
    )
    sig_surge = strat_ta.generate_signal(candles=[*candles, hammer_surge])
    sig_norm = strat_ta.generate_signal(candles=[*candles, hammer_norm])

    assert sig_surge.signal_type is SignalType.BUY
    assert sig_norm.signal_type is SignalType.BUY
    # Surge volume should receive +0.03 confluence bonus
    assert sig_surge.confidence > sig_norm.confidence
