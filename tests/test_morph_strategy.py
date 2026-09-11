"""
Botragram

Description:
    Unit tests for Market Orderflow Regime & Price-Hunt (MORPH) strategy.

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
from botragram.strategies import StrategyFactory
from botragram.strategies.price_action.morph import MorphStrategy

_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _make_candle(
    *,
    index: int,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
    volume: Decimal = Decimal("100.0"),
    open_interest: Decimal | None = None,
    funding_rate: Decimal | None = None,
) -> Candle:
    """Helper to construct a timestamped test candle."""
    open_time = _NOW + timedelta(minutes=15 * index)
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
        open_interest=open_interest,
        funding_rate=funding_rate,
    )


def _build_initial_candles(count: int = 15) -> list[Candle]:
    """Generate initial neutral background candles."""
    candles: list[Candle] = []
    for i in range(count):
        candles.append(
            _make_candle(
                index=i,
                open_price=Decimal("110.0"),
                high_price=Decimal("112.0"),
                low_price=Decimal("108.0"),
                close_price=Decimal("110.5"),
                volume=Decimal("100.0"),
                open_interest=Decimal("1000.0"),
            )
        )
    return candles


# =============================================================================
# Unit Tests
# =============================================================================
def test_morph_strategy_properties() -> None:
    """Test strategy type, minimum candles, and parameter validations."""
    strategy = MorphStrategy(
        swing_lookback=10,
        volume_period=10,
        atr_period=10,
        require_trend_filter=False,
    )
    assert strategy.strategy_type is StrategyType.MORPH
    assert strategy.minimum_candles >= 20

    with pytest.raises(ValueError, match="swing_lookback must be greater than 2"):
        MorphStrategy(swing_lookback=2)

    with pytest.raises(ValueError, match="min_confidence must be between 0.0 and 1.0"):
        MorphStrategy(min_confidence=Decimal("1.5"))

    with pytest.raises(ValueError, match="trend_period must be greater than zero"):
        MorphStrategy(trend_period=0)

    with pytest.raises(ValueError, match="intermediate_trend_period must be less"):
        MorphStrategy(trend_period=50, intermediate_trend_period=50)


def test_morph_strategy_factory_resolution() -> None:
    """Test StrategyFactory resolves MORPH strategy instance."""
    settings = StrategySettings(
        strategy_type=StrategyType.MORPH,
        morph_swing_lookback=12,
        morph_volume_multiplier=Decimal("1.2"),
    )
    strat = StrategyFactory.create(settings=settings)
    assert isinstance(strat, MorphStrategy)
    assert strat.swing_lookback == 12
    assert strat.volume_multiplier == Decimal("1.2")


def test_morph_strategy_bullish_liquidity_sweep_and_pinbar() -> None:
    """Test Bullish Liquidity Sweep of swing low followed by pinbar rejection."""
    strategy = MorphStrategy(
        swing_lookback=5,
        volume_period=5,
        atr_period=5,
        volume_multiplier=Decimal("1.10"),
        use_fvg=False,
        use_open_interest=False,
        require_trend_filter=False,
    )

    candles = _build_initial_candles(15)
    start_idx = len(candles)

    # Add candles with a confirmed swing low at index 5 relative to this block
    base_prices = [
        (110.0, 112.0, 108.0, 111.0),
        (111.0, 113.0, 109.0, 110.0),
        (110.0, 111.0, 107.0, 108.0),
        (108.0, 109.0, 105.0, 106.0),
        (106.0, 107.0, 104.0, 105.0),
        # Confirmed Swing Low at 100.0
        (105.0, 106.0, 100.0, 103.0),
        (103.0, 107.0, 102.0, 106.0),
        (106.0, 108.0, 104.0, 107.0),
        (107.0, 110.0, 105.0, 109.0),
        (109.0, 111.0, 106.0, 108.0),
        (108.0, 110.0, 105.0, 107.0),
        # Pre-trigger candle
        (107.0, 108.0, 103.0, 104.0),
    ]

    for i, (op, hp, lp, cp) in enumerate(base_prices):
        candles.append(
            _make_candle(
                index=start_idx + i,
                open_price=Decimal(str(op)),
                high_price=Decimal(str(hp)),
                low_price=Decimal(str(lp)),
                close_price=Decimal(str(cp)),
                volume=Decimal("100.0"),
            )
        )

    # Trigger candle:
    # Dips below 100.0 (low = 98.0) and closes at 104.0 -> Bullish Sweep!
    # Lower wick = 5.0, range = 6.5 (wick ratio ~0.77, Bullish Pinbar)
    trigger_candle = _make_candle(
        index=len(candles),
        open_price=Decimal("103.0"),
        high_price=Decimal("104.5"),
        low_price=Decimal("98.0"),
        close_price=Decimal("104.0"),
        volume=Decimal("200.0"),
    )
    candles.append(trigger_candle)

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.BUY
    assert signal.confidence >= Decimal("0.70")
    assert "Bullish Sweep" in (signal.reason or "")
    assert "Invalidation:" in (signal.reason or "")


def test_morph_strategy_bearish_liquidity_sweep_and_pinbar() -> None:
    """Test Bearish Liquidity Sweep of swing high followed by shooting star pinbar."""
    strategy = MorphStrategy(
        swing_lookback=5,
        volume_period=5,
        atr_period=5,
        volume_multiplier=Decimal("1.10"),
        use_fvg=False,
        use_open_interest=False,
        require_trend_filter=False,
    )

    candles = _build_initial_candles(15)
    start_idx = len(candles)

    # Confirmed swing high at 200.0
    base_prices = [
        (180.0, 185.0, 178.0, 184.0),
        (184.0, 188.0, 182.0, 186.0),
        (186.0, 190.0, 185.0, 189.0),
        (189.0, 193.0, 187.0, 192.0),
        (192.0, 196.0, 190.0, 195.0),
        # Swing High at 200.0
        (195.0, 200.0, 194.0, 198.0),
        (198.0, 199.0, 192.0, 194.0),
        (194.0, 196.0, 190.0, 192.0),
        (192.0, 195.0, 188.0, 190.0),
        (190.0, 193.0, 187.0, 189.0),
        (189.0, 192.0, 186.0, 188.0),
        # Pre-trigger candle
        (188.0, 194.0, 187.0, 193.0),
    ]

    for i, (op, hp, lp, cp) in enumerate(base_prices):
        candles.append(
            _make_candle(
                index=start_idx + i,
                open_price=Decimal(str(op)),
                high_price=Decimal(str(hp)),
                low_price=Decimal(str(lp)),
                close_price=Decimal(str(cp)),
                volume=Decimal("100.0"),
            )
        )

    # Trigger candle: Pierces above 200.0 to 203.0 and closes down at 195.0
    trigger_candle = _make_candle(
        index=len(candles),
        open_price=Decimal("196.0"),
        high_price=Decimal("203.0"),
        low_price=Decimal("194.0"),
        close_price=Decimal("195.0"),
        volume=Decimal("250.0"),
    )
    candles.append(trigger_candle)

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.SELL
    assert signal.confidence >= Decimal("0.70")
    assert "Bearish Sweep" in (signal.reason or "")
    assert "Target:" in (signal.reason or "")


def test_morph_strategy_low_volume_rejected() -> None:
    """Test setup is rejected (HOLD) when volume fails participation threshold."""
    strategy = MorphStrategy(
        swing_lookback=5,
        volume_period=5,
        atr_period=5,
        volume_multiplier=Decimal("1.50"),
        use_fvg=False,
        use_open_interest=False,
        require_trend_filter=False,
    )

    candles = _build_initial_candles(15)
    start_idx = len(candles)

    base_prices = [
        (110.0, 112.0, 108.0, 111.0),
        (111.0, 113.0, 109.0, 110.0),
        (110.0, 111.0, 107.0, 108.0),
        (108.0, 109.0, 105.0, 106.0),
        (106.0, 107.0, 104.0, 105.0),
        (105.0, 106.0, 100.0, 103.0),
        (103.0, 107.0, 102.0, 106.0),
        (106.0, 108.0, 104.0, 107.0),
        (107.0, 110.0, 105.0, 109.0),
        (109.0, 111.0, 106.0, 108.0),
        (108.0, 110.0, 105.0, 107.0),
        (107.0, 108.0, 103.0, 104.0),
    ]

    for i, (op, hp, lp, cp) in enumerate(base_prices):
        candles.append(
            _make_candle(
                index=start_idx + i,
                open_price=Decimal(str(op)),
                high_price=Decimal(str(hp)),
                low_price=Decimal(str(lp)),
                close_price=Decimal(str(cp)),
                volume=Decimal("100.0"),
            )
        )

    # Bullish sweep, but low volume = 50.0 (below 100 * 1.5)
    trigger_candle = _make_candle(
        index=len(candles),
        open_price=Decimal("103.0"),
        high_price=Decimal("104.5"),
        low_price=Decimal("98.0"),
        close_price=Decimal("104.0"),
        volume=Decimal("50.0"),
    )
    candles.append(trigger_candle)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "Volume below participation threshold" in (signal.reason or "")


def test_morph_strategy_no_hunt_in_mid_range() -> None:
    """Test that pinbar in the middle of a range without sweep produces HOLD."""
    strategy = MorphStrategy(
        swing_lookback=5,
        volume_period=5,
        atr_period=5,
        use_fvg=False,
        use_open_interest=False,
        require_trend_filter=False,
    )

    candles = _build_initial_candles(15)
    start_idx = len(candles)

    base_prices = [
        (110.0, 112.0, 108.0, 111.0),
        (111.0, 113.0, 109.0, 110.0),
        (110.0, 111.0, 107.0, 108.0),
        (108.0, 109.0, 105.0, 106.0),
        (106.0, 107.0, 104.0, 105.0),
        (105.0, 106.0, 100.0, 103.0),
        (103.0, 107.0, 102.0, 106.0),
        (106.0, 108.0, 104.0, 107.0),
        (107.0, 110.0, 105.0, 109.0),
        (109.0, 111.0, 106.0, 108.0),
        (108.0, 110.0, 105.0, 107.0),
        (107.0, 108.0, 103.0, 104.0),
    ]

    for i, (op, hp, lp, cp) in enumerate(base_prices):
        candles.append(
            _make_candle(
                index=start_idx + i,
                open_price=Decimal(str(op)),
                high_price=Decimal(str(hp)),
                low_price=Decimal(str(lp)),
                close_price=Decimal(str(cp)),
                volume=Decimal("100.0"),
            )
        )

    # Pinbar at 106.0 (mid-range, far above 100.0 and far below 113.0) -> No sweep!
    mid_candle = _make_candle(
        index=len(candles),
        open_price=Decimal("106.0"),
        high_price=Decimal("107.0"),
        low_price=Decimal("104.0"),
        close_price=Decimal("106.8"),
        volume=Decimal("300.0"),
    )
    candles.append(mid_candle)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "No liquidity sweep or FVG price-hunt detected" in (signal.reason or "")


def test_morph_strategy_with_open_interest_integration() -> None:
    """Test MORPH enhances signal confidence when Open Interest aligns."""
    strategy = MorphStrategy(
        swing_lookback=5,
        volume_period=5,
        atr_period=5,
        volume_multiplier=Decimal("1.10"),
        use_fvg=False,
        use_open_interest=True,
        oi_confidence_bonus=Decimal("0.05"),
        require_oi_confluence=False,
        require_trend_filter=False,
    )

    candles = _build_initial_candles(15)
    start_idx = len(candles)

    base_prices = [
        (110.0, 112.0, 108.0, 111.0),
        (111.0, 113.0, 109.0, 110.0),
        (110.0, 111.0, 107.0, 108.0),
        (108.0, 109.0, 105.0, 106.0),
        (106.0, 107.0, 104.0, 105.0),
        (105.0, 106.0, 100.0, 103.0),
        (103.0, 107.0, 102.0, 106.0),
        (106.0, 108.0, 104.0, 107.0),
        (107.0, 110.0, 105.0, 109.0),
        (109.0, 111.0, 106.0, 108.0),
        (108.0, 110.0, 105.0, 107.0),
        (107.0, 108.0, 103.0, 104.0),
    ]

    for i, (op, hp, lp, cp) in enumerate(base_prices):
        candles.append(
            _make_candle(
                index=start_idx + i,
                open_price=Decimal(str(op)),
                high_price=Decimal(str(hp)),
                low_price=Decimal(str(lp)),
                close_price=Decimal(str(cp)),
                volume=Decimal("100.0"),
                open_interest=Decimal("1000.0"),
            )
        )

    # Bullish sweep trigger candle with expanding OI (+50 contracts = LONG_BUILDUP!)
    trigger_candle = _make_candle(
        index=len(candles),
        open_price=Decimal("103.0"),
        high_price=Decimal("104.5"),
        low_price=Decimal("98.0"),
        close_price=Decimal("104.0"),
        volume=Decimal("200.0"),
        open_interest=Decimal("1050.0"),
    )
    candles.append(trigger_candle)

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.BUY
    assert signal.confidence >= Decimal("0.75")
    assert "Long Buildup" in (signal.reason or "")


def test_morph_strategy_macro_trend_filter_blocks_counter_trend() -> None:
    """Test macro trend filter rejects counter-trend buy in macro downtrend."""
    # Trend period 10, intermediate period 5
    strategy = MorphStrategy(
        swing_lookback=4,
        fvg_lookback=5,
        volume_period=4,
        atr_period=4,
        volume_multiplier=Decimal("1.10"),
        use_fvg=False,
        use_open_interest=False,
        trend_period=10,
        intermediate_trend_period=5,
        require_trend_filter=True,
    )

    # Create 25 downtrending candles (price falling from 150 to 75)
    candles: list[Candle] = []
    for i in range(25):
        p = Decimal(str(150 - i * 3))
        candles.append(
            _make_candle(
                index=i,
                open_price=p,
                high_price=p + Decimal("2.0"),
                low_price=p - Decimal("2.0"),
                close_price=p - Decimal("1.0"),
                volume=Decimal("100.0"),
            )
        )

    # Trigger candle
    trigger_candle = _make_candle(
        index=25,
        open_price=Decimal("74.0"),
        high_price=Decimal("78.0"),
        low_price=Decimal("70.0"),
        close_price=Decimal("77.0"),
        volume=Decimal("300.0"),
    )
    candles.append(trigger_candle)

    signal = strategy.generate_signal(candles=candles)
    # In macro downtrend (close < EMA 10), bullish setup must be rejected
    assert signal.signal_type is SignalType.HOLD
    assert "rejected: below trend EMA or macro downtrend" in (
        signal.reason or ""
    ) or "No liquidity sweep" in (signal.reason or "")


def test_morph_strategy_dead_market_natr_rejected() -> None:
    """Test dead market volatility gate rejects signals when NATR is below threshold."""
    strategy = MorphStrategy(
        swing_lookback=5,
        volume_period=5,
        atr_period=5,
        volume_multiplier=Decimal("1.10"),
        use_fvg=False,
        use_open_interest=False,
        require_trend_filter=False,
        min_natr_threshold=Decimal("0.50"),  # Impossibly high NATR to trigger rejection
    )

    candles = _build_initial_candles(15)
    start_idx = len(candles)

    base_prices = [
        (110.0, 112.0, 108.0, 111.0),
        (111.0, 113.0, 109.0, 110.0),
        (110.0, 111.0, 107.0, 108.0),
        (108.0, 109.0, 105.0, 106.0),
        (106.0, 107.0, 104.0, 105.0),
        (105.0, 106.0, 100.0, 103.0),
        (103.0, 107.0, 102.0, 106.0),
        (106.0, 108.0, 104.0, 107.0),
        (107.0, 110.0, 105.0, 109.0),
        (109.0, 111.0, 106.0, 108.0),
        (108.0, 110.0, 105.0, 107.0),
        (107.0, 108.0, 103.0, 104.0),
    ]

    for i, (op, hp, lp, cp) in enumerate(base_prices):
        candles.append(
            _make_candle(
                index=start_idx + i,
                open_price=Decimal(str(op)),
                high_price=Decimal(str(hp)),
                low_price=Decimal(str(lp)),
                close_price=Decimal(str(cp)),
                volume=Decimal("100.0"),
            )
        )

    trigger_candle = _make_candle(
        index=len(candles),
        open_price=Decimal("103.0"),
        high_price=Decimal("104.5"),
        low_price=Decimal("98.0"),
        close_price=Decimal("104.0"),
        volume=Decimal("200.0"),
    )
    candles.append(trigger_candle)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "Dead market volatility rejected" in (signal.reason or "")


def test_morph_strategy_excessive_long_funding_rejected() -> None:
    """Test candidate BUY rejected when funding rate exceeds +0.05%."""
    strategy = MorphStrategy(
        swing_lookback=5,
        volume_period=5,
        atr_period=5,
        volume_multiplier=Decimal("1.10"),
        use_fvg=False,
        use_open_interest=False,
        filter_funding_sentiment=True,
        max_long_funding_rate=Decimal("0.0005"),
        require_funding_sentiment=True,
        require_trend_filter=False,
    )

    candles = _build_initial_candles(15)
    start_idx = len(candles)

    base_prices = [
        (110.0, 112.0, 108.0, 111.0),
        (111.0, 113.0, 109.0, 110.0),
        (110.0, 111.0, 107.0, 108.0),
        (108.0, 109.0, 105.0, 106.0),
        (106.0, 107.0, 104.0, 105.0),
        (105.0, 106.0, 100.0, 103.0),
        (103.0, 107.0, 102.0, 106.0),
        (106.0, 108.0, 104.0, 107.0),
        (107.0, 110.0, 105.0, 109.0),
        (109.0, 111.0, 106.0, 108.0),
        (108.0, 110.0, 105.0, 107.0),
        (107.0, 108.0, 103.0, 104.0),
    ]

    for i, (op, hp, lp, cp) in enumerate(base_prices):
        candles.append(
            _make_candle(
                index=start_idx + i,
                open_price=Decimal(str(op)),
                high_price=Decimal(str(hp)),
                low_price=Decimal(str(lp)),
                close_price=Decimal(str(cp)),
                volume=Decimal("100.0"),
            )
        )

    # Bullish sweep trigger candle, but extreme positive funding rate (+0.08%)
    trigger_candle = _make_candle(
        index=len(candles),
        open_price=Decimal("103.0"),
        high_price=Decimal("104.5"),
        low_price=Decimal("98.0"),
        close_price=Decimal("104.0"),
        volume=Decimal("200.0"),
        funding_rate=Decimal("0.0008"),
    )
    candles.append(trigger_candle)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert "[REJECTED_FUNDING_CROWDED]" in (signal.reason or "")
    assert "Excessive long funding" in (signal.reason or "")


def test_morph_strategy_normal_funding_preserves_buy() -> None:
    """Test candidate BUY retained when funding rate is normal (+0.01%)."""
    strategy = MorphStrategy(
        swing_lookback=5,
        volume_period=5,
        atr_period=5,
        volume_multiplier=Decimal("1.10"),
        use_fvg=False,
        use_open_interest=False,
        filter_funding_sentiment=True,
        max_long_funding_rate=Decimal("0.0005"),
        require_funding_sentiment=True,
        require_trend_filter=False,
    )

    candles = _build_initial_candles(15)
    start_idx = len(candles)

    base_prices = [
        (110.0, 112.0, 108.0, 111.0),
        (111.0, 113.0, 109.0, 110.0),
        (110.0, 111.0, 107.0, 108.0),
        (108.0, 109.0, 105.0, 106.0),
        (106.0, 107.0, 104.0, 105.0),
        (105.0, 106.0, 100.0, 103.0),
        (103.0, 107.0, 102.0, 106.0),
        (106.0, 108.0, 104.0, 107.0),
        (107.0, 110.0, 105.0, 109.0),
        (109.0, 111.0, 106.0, 108.0),
        (108.0, 110.0, 105.0, 107.0),
        (107.0, 108.0, 103.0, 104.0),
    ]

    for i, (op, hp, lp, cp) in enumerate(base_prices):
        candles.append(
            _make_candle(
                index=start_idx + i,
                open_price=Decimal(str(op)),
                high_price=Decimal(str(hp)),
                low_price=Decimal(str(lp)),
                close_price=Decimal(str(cp)),
                volume=Decimal("100.0"),
            )
        )

    # Bullish sweep trigger candle with healthy funding (+0.01%)
    trigger_candle = _make_candle(
        index=len(candles),
        open_price=Decimal("103.0"),
        high_price=Decimal("104.5"),
        low_price=Decimal("98.0"),
        close_price=Decimal("104.0"),
        volume=Decimal("200.0"),
        funding_rate=Decimal("0.0001"),
    )
    candles.append(trigger_candle)

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.BUY
    assert "[REJECTED_FUNDING_CROWDED]" not in (signal.reason or "")
