"""
Botragram

Description:
    Unit tests for NY_4H_Range_Scalping strategy.

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
from zoneinfo import ZoneInfo

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, SignalType
from botragram.models import Candle
from botragram.strategies.scalping.ny_4h_range_scalping import (
    NY4HRangeScalpingStrategy,
)

# =============================================================================
# Constants
# =============================================================================
_NY_TZ = ZoneInfo("America/New_York")


# =============================================================================
# Fixture Helpers
# =============================================================================
def _make_candle(
    *,
    symbol: str = "BTCUSDT",
    ny_dt: datetime,
    open_price: str | Decimal,
    high_price: str | Decimal,
    low_price: str | Decimal,
    close_price: str | Decimal,
    volume: str | Decimal = "100",
    open_interest: str | Decimal | None = None,
) -> Candle:
    """Helper to construct a Candle fixture with timezone-aware NY datetime."""
    # Ensure ny_dt has America/New_York timezone attached
    if ny_dt.tzinfo is None:
        ny_dt = ny_dt.replace(tzinfo=_NY_TZ)

    utc_open = ny_dt.astimezone(timezone.utc)
    utc_close = utc_open + timedelta(minutes=5)

    return Candle(
        symbol=symbol,
        interval=Interval.M5,
        open_time=utc_open,
        close_time=utc_close,
        open_price=Decimal(str(open_price)),
        high_price=Decimal(str(high_price)),
        low_price=Decimal(str(low_price)),
        close_price=Decimal(str(close_price)),
        volume=Decimal(str(volume)),
        open_interest=Decimal(str(open_interest)) if open_interest else None,
    )


def _build_initial_4h_block(
    *,
    trading_date: datetime,
    range_high: str = "105.0",
    range_low: str = "95.0",
) -> list[Candle]:
    """Construct 48 5-minute candles covering 00:00 to 03:55 NY time."""
    candles: list[Candle] = []
    base_dt = trading_date.replace(hour=0, minute=0, second=0, microsecond=0)

    for i in range(48):
        c_time = base_dt + timedelta(minutes=5 * i)
        # Seed range_high on one candle and range_low on another
        if i == 10:
            high_val, low_val = range_high, "100.0"
        elif i == 20:
            high_val, low_val = "100.0", range_low
        else:
            high_val, low_val = "102.0", "98.0"

        candles.append(
            _make_candle(
                ny_dt=c_time,
                open_price="100.0",
                high_price=high_val,
                low_price=low_val,
                close_price="100.0",
            )
        )

    return candles


# =============================================================================
# Tests
# =============================================================================
def test_ny_4h_range_scalping_holds_during_initial_4h_window() -> None:
    """Verify strategy returns HOLD while the 4H range is still forming (< 04:00 NY)."""
    strategy = NY4HRangeScalpingStrategy()
    base_date = datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ)

    # 40 candles covering 00:00 to 03:15 NY (plus 10 prior candles to meet minimum 50)
    prior_candles = [
        _make_candle(
            ny_dt=base_date - timedelta(minutes=5 * (15 - i)),
            open_price="100.0",
            high_price="101.0",
            low_price="99.0",
            close_price="100.0",
        )
        for i in range(15)
    ]
    current_day_candles = [
        _make_candle(
            ny_dt=base_date + timedelta(minutes=5 * i),
            open_price="100.0",
            high_price="102.0",
            low_price="98.0",
            close_price="100.0",
        )
        for i in range(38)  # up to 03:05 NY
    ]
    all_candles = prior_candles + current_day_candles
    assert len(all_candles) >= strategy.minimum_candles

    signal = strategy.generate_signal(candles=all_candles)
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None and "NY 4H initial range forming" in signal.reason
    assert signal.stop_loss is None
    assert signal.take_profit is None


def test_ny_4h_range_scalping_short_setup() -> None:
    """Verify short setup: breakout closes > Range_High, next closes < Range_High."""
    strategy = NY4HRangeScalpingStrategy(
        risk_reward_ratio=Decimal("2.0"),
        max_sl_pct=Decimal("0.10"),  # allow wide swing for clear math
    )
    base_date = datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ)

    # 48 candles (00:00 to 03:55 NY), Range_High = 105.0, Range_Low = 95.0
    candles = _build_initial_4h_block(
        trading_date=base_date,
        range_high="105.0",
        range_low="95.0",
    )
    # Add candle at 04:00 NY (inside range)
    dt_0400 = base_date.replace(hour=4, minute=0)
    candles.append(
        _make_candle(
            ny_dt=dt_0400,
            open_price="100.0",
            high_price="102.0",
            low_price="99.0",
            close_price="101.0",
        )
    )
    # Candle at 04:05 NY: Breakout closing ABOVE Range_High (close=108.0, high=110.0)
    dt_0405 = base_date.replace(hour=4, minute=5)
    candles.append(
        _make_candle(
            ny_dt=dt_0405,
            open_price="101.0",
            high_price="110.0",
            low_price="100.5",
            close_price="108.0",
        )
    )
    # Candle at 04:10 NY: Re-entry closing BELOW Range_High (close=103.0, high=104.0)
    dt_0410 = base_date.replace(hour=4, minute=10)
    candles.append(
        _make_candle(
            ny_dt=dt_0410,
            open_price="108.0",
            high_price="108.0",
            low_price="102.5",
            close_price="103.0",
        )
    )

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.SELL
    assert signal.price == Decimal("103.0")
    # Swing high of the breakout candle is 110.0
    assert signal.stop_loss == Decimal("110.0")
    # SL distance = 110.0 - 103.0 = 7.0. TP distance = 2 * 7.0 = 14.0.
    # Take profit = 103.0 - 14.0 = 89.0
    assert signal.take_profit == Decimal("89.0")
    assert signal.confidence >= strategy.min_confidence
    assert signal.reason is not None and "NY 4H Short" in signal.reason


def test_ny_4h_range_scalping_long_setup() -> None:
    """Verify long setup: breakout closes < Range_Low, next closes > Range_Low."""
    strategy = NY4HRangeScalpingStrategy(
        risk_reward_ratio=Decimal("2.0"),
        max_sl_pct=Decimal("0.10"),
    )
    base_date = datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ)

    candles = _build_initial_4h_block(
        trading_date=base_date,
        range_high="105.0",
        range_low="95.0",
    )
    # 04:00 NY candle (inside range)
    dt_0400 = base_date.replace(hour=4, minute=0)
    candles.append(
        _make_candle(
            ny_dt=dt_0400,
            open_price="100.0",
            high_price="101.0",
            low_price="98.0",
            close_price="99.0",
        )
    )
    # 04:05 NY: Breakout closing BELOW Range_Low (close=92.0 < 95.0, low=90.0)
    dt_0405 = base_date.replace(hour=4, minute=5)
    candles.append(
        _make_candle(
            ny_dt=dt_0405,
            open_price="99.0",
            high_price="99.0",
            low_price="90.0",
            close_price="92.0",
        )
    )
    # 04:10 NY: Re-entry closing ABOVE Range_Low (close=97.0 > 95.0, low=96.0)
    dt_0410 = base_date.replace(hour=4, minute=10)
    candles.append(
        _make_candle(
            ny_dt=dt_0410,
            open_price="92.0",
            high_price="98.0",
            low_price="92.0",
            close_price="97.0",
        )
    )

    signal = strategy.generate_signal(candles=candles)

    assert signal.signal_type is SignalType.BUY
    assert signal.price == Decimal("97.0")
    # Swing low of the breakout candle is 90.0
    assert signal.stop_loss == Decimal("90.0")
    # SL distance = 97.0 - 90.0 = 7.0. TP distance = 2 * 7.0 = 14.0.
    # Take profit = 97.0 + 14.0 = 111.0
    assert signal.take_profit == Decimal("111.0")
    assert signal.confidence >= strategy.min_confidence
    assert signal.reason is not None and "NY 4H Long" in signal.reason


def test_ny_4h_range_scalping_ignores_wick_only_breakout() -> None:
    """Verify that wick exceeding Range_High without close does not trigger short."""
    strategy = NY4HRangeScalpingStrategy()
    base_date = datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ)

    candles = _build_initial_4h_block(
        trading_date=base_date,
        range_high="105.0",
        range_low="95.0",
    )
    # 04:00 NY: Wick reaches 110.0, but CLOSE is 104.0 (inside range)
    dt_0400 = base_date.replace(hour=4, minute=0)
    candles.append(
        _make_candle(
            ny_dt=dt_0400,
            open_price="100.0",
            high_price="110.0",
            low_price="100.0",
            close_price="104.0",
        )
    )
    # 04:05 NY: Inside range (close=103.0)
    dt_0405 = base_date.replace(hour=4, minute=5)
    candles.append(
        _make_candle(
            ny_dt=dt_0405,
            open_price="104.0",
            high_price="104.5",
            low_price="102.5",
            close_price="103.0",
        )
    )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None and "Within NY 4H range" in signal.reason


def test_ny_4h_range_scalping_bounds_excessive_sl() -> None:
    """Verify fallback cap when breakout swing SL distance exceeds max_sl_pct."""
    max_sl = Decimal("0.02")  # 2.0% max SL
    strategy = NY4HRangeScalpingStrategy(
        risk_reward_ratio=Decimal("2.0"),
        max_sl_pct=max_sl,
    )
    base_date = datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ)

    candles = _build_initial_4h_block(
        trading_date=base_date,
        range_high="105.0",
        range_low="95.0",
    )
    # 04:00 NY: inside range
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=0),
            open_price="100.0",
            high_price="101.0",
            low_price="99.0",
            close_price="100.0",
        )
    )
    # 04:05 NY: Breakout to 125.0 (huge 25% wick!)
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=5),
            open_price="100.0",
            high_price="125.0",
            low_price="100.0",
            close_price="107.0",
        )
    )
    # 04:10 NY: Re-entry closing at 100.0
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=10),
            open_price="107.0",
            high_price="107.0",
            low_price="99.5",
            close_price="100.0",
        )
    )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.SELL
    # SL should be capped to 100.0 * (1 + 0.02) = 102.0 instead of 125.0!
    assert signal.stop_loss == Decimal("102.0")
    # Take profit = 100.0 - 2 * 2.0 = 96.0
    assert signal.take_profit == Decimal("96.0")


def test_ny_4h_range_scalping_day_transition_reset() -> None:
    """Verify that candles crossing into next day reset range and hold before 04:00."""
    strategy = NY4HRangeScalpingStrategy()
    day1_base = datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ)

    candles = _build_initial_4h_block(
        trading_date=day1_base,
        range_high="105.0",
        range_low="95.0",
    )
    # Add Day 2 early morning candles at 01:00 and 01:05 NY
    candles.append(
        _make_candle(
            ny_dt=datetime(2026, 6, 16, 1, 0, tzinfo=_NY_TZ),
            open_price="100.0",
            high_price="101.0",
            low_price="99.0",
            close_price="100.0",
        )
    )
    candles.append(
        _make_candle(
            ny_dt=datetime(2026, 6, 16, 1, 5, tzinfo=_NY_TZ),
            open_price="100.0",
            high_price="101.0",
            low_price="99.0",
            close_price="100.0",
        )
    )

    signal = strategy.generate_signal(candles=candles)
    # Since latest candle is on June 16 at 01:05 NY, range is forming
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None and "NY 4H initial range forming" in signal.reason


def test_ny_4h_range_scalping_validations() -> None:
    """Verify parameter and candle invariant checks."""
    with pytest.raises(ValueError, match="risk_reward_ratio must be positive"):
        NY4HRangeScalpingStrategy(risk_reward_ratio=Decimal("0"))

    with pytest.raises(ValueError, match="min_sl_pct cannot exceed max_sl_pct"):
        NY4HRangeScalpingStrategy(
            min_sl_pct=Decimal("0.05"),
            max_sl_pct=Decimal("0.01"),
        )

    with pytest.raises(ValueError, match="volume_period must be greater than zero"):
        NY4HRangeScalpingStrategy(volume_period=0)

    with pytest.raises(ValueError, match="volume_multiplier must not be negative"):
        NY4HRangeScalpingStrategy(volume_multiplier=Decimal("-1.0"))

    with pytest.raises(
        ValueError, match="volume_confidence_bonus must not be negative"
    ):
        NY4HRangeScalpingStrategy(volume_confidence_bonus=Decimal("-0.1"))

    with pytest.raises(ValueError, match="trend_ema_period must be greater than zero"):
        NY4HRangeScalpingStrategy(trend_ema_period=0)

    with pytest.raises(ValueError, match="rsi_period must be greater than zero"):
        NY4HRangeScalpingStrategy(rsi_period=0)

    with pytest.raises(ValueError, match="rsi_long_max must be between 0.0 and 100.0"):
        NY4HRangeScalpingStrategy(rsi_long_max=Decimal("101.0"))

    with pytest.raises(ValueError, match="rsi_short_min must be between 0.0 and 100.0"):
        NY4HRangeScalpingStrategy(rsi_short_min=Decimal("-1.0"))

    strategy = NY4HRangeScalpingStrategy()
    # Less than 50 candles
    few_candles = [
        _make_candle(
            ny_dt=datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ),
            open_price="100",
            high_price="101",
            low_price="99",
            close_price="100",
        )
    ]
    with pytest.raises(ValueError, match="requires at least 50 candles"):
        strategy.generate_signal(candles=few_candles)


def test_ny_4h_range_scalping_volume_confirmation() -> None:
    """Verify that volume confirmation elevates confidence above min_confidence."""
    base_date = datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ)
    # Range high = 105, range low = 95
    candles = _build_initial_4h_block(
        trading_date=base_date,
        range_high="105.0",
        range_low="95.0",
    )
    # 04:00 inside range
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=0),
            open_price="100.0",
            high_price="101.0",
            low_price="98.0",
            close_price="99.0",
            volume="100",
        )
    )
    # 04:05 breakout below 95
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=5),
            open_price="99.0",
            high_price="99.0",
            low_price="90.0",
            close_price="92.0",
            volume="100",
        )
    )

    # Case A: Low volume re-entry (volume=50 < avg 100).
    # Base confidence = 0.70, min_confidence = 0.75.
    # Without volume bonus, confidence remains 0.70 < 0.75 -> HOLD
    low_vol_candles = list(candles)
    low_vol_candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=10),
            open_price="92.0",
            high_price="98.0",
            low_price="92.0",
            close_price="97.0",
            volume="50",
        )
    )
    strategy = NY4HRangeScalpingStrategy(
        base_confidence=Decimal("0.70"),
        min_confidence=Decimal("0.75"),
        use_volume_filter=True,
        volume_period=20,
        volume_multiplier=Decimal("1.0"),
        volume_confidence_bonus=Decimal("0.10"),
    )
    signal_low = strategy.generate_signal(candles=low_vol_candles)
    assert signal_low.signal_type is SignalType.HOLD
    assert (
        signal_low.reason is not None
        and "Confidence 0.70 below threshold 0.75" in signal_low.reason
    )

    # Case B: High volume re-entry (volume=150 >= avg 100).
    # Confidence is boosted: 0.70 + 0.10 = 0.80 >= 0.75 -> BUY signal generated!
    high_vol_candles = list(candles)
    high_vol_candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=10),
            open_price="92.0",
            high_price="98.0",
            low_price="92.0",
            close_price="97.0",
            volume="150",
        )
    )
    signal_high = strategy.generate_signal(candles=high_vol_candles)
    assert signal_high.signal_type is SignalType.BUY
    assert signal_high.confidence == Decimal("0.80")


def test_ny_4h_range_scalping_trend_filter() -> None:
    """Verify that require_trend_filter blocks counter-trend setups."""
    base_date = datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ)
    # Construct block with high prices so 50 EMA is high (e.g. ~100)
    candles = _build_initial_4h_block(
        trading_date=base_date,
        range_high="105.0",
        range_low="95.0",
    )
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=0),
            open_price="100.0",
            high_price="101.0",
            low_price="98.0",
            close_price="99.0",
            volume="100",
        )
    )
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=5),
            open_price="99.0",
            high_price="99.0",
            low_price="90.0",
            close_price="92.0",
            volume="100",
        )
    )
    # Re-entry price 97.0 which is well below the EMA (~100.0)
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=10),
            open_price="92.0",
            high_price="98.0",
            low_price="92.0",
            close_price="97.0",
            volume="150",
        )
    )

    strategy_with_trend = NY4HRangeScalpingStrategy(
        require_trend_filter=True,
        trend_ema_period=10,
        min_confidence=Decimal("0.70"),
    )
    signal = strategy_with_trend.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None and "Counter-trend BUY below EMA" in signal.reason


def test_ny_4h_range_scalping_rsi_filter_blocks_long() -> None:
    """Verify that use_rsi_filter blocks long when RSI exceeds rsi_long_max."""
    base_date = datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ)
    candles = _build_initial_4h_block(
        trading_date=base_date,
        range_high="105.0",
        range_low="95.0",
    )
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=0),
            open_price="100.0",
            high_price="101.0",
            low_price="98.0",
            close_price="99.0",
            volume="100",
        )
    )
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=5),
            open_price="99.0",
            high_price="99.0",
            low_price="90.0",
            close_price="92.0",
            volume="100",
        )
    )
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=10),
            open_price="92.0",
            high_price="98.0",
            low_price="92.0",
            close_price="97.0",
            volume="150",
        )
    )

    # With rsi_long_max set strictly to 30.0, current RSI (~40.0) is rejected
    strategy_rsi = NY4HRangeScalpingStrategy(
        use_rsi_filter=True,
        rsi_long_max=Decimal("30.0"),
        min_confidence=Decimal("0.70"),
    )
    signal = strategy_rsi.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None and "above long ceiling" in signal.reason


def test_ny_4h_range_scalping_rsi_filter_blocks_short() -> None:
    """Verify that use_rsi_filter blocks short when RSI is below rsi_short_min."""
    base_date = datetime(2026, 6, 15, 0, 0, tzinfo=_NY_TZ)
    candles = _build_initial_4h_block(
        trading_date=base_date,
        range_high="105.0",
        range_low="95.0",
    )
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=0),
            open_price="100.0",
            high_price="102.0",
            low_price="99.0",
            close_price="101.0",
        )
    )
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=5),
            open_price="101.0",
            high_price="110.0",
            low_price="100.5",
            close_price="108.0",
        )
    )
    candles.append(
        _make_candle(
            ny_dt=base_date.replace(hour=4, minute=10),
            open_price="108.0",
            high_price="108.0",
            low_price="102.5",
            close_price="103.0",
        )
    )

    # With rsi_short_min set strictly to 75.0, current RSI (~58.0) is rejected
    strategy_rsi = NY4HRangeScalpingStrategy(
        use_rsi_filter=True,
        rsi_short_min=Decimal("75.0"),
        min_confidence=Decimal("0.70"),
    )
    signal = strategy_rsi.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.HOLD
    assert signal.reason is not None and "below short floor" in signal.reason
