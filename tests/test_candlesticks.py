"""
Botragram

Description:
    Tests for mathematical candlestick pattern detection indicators.

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
# Local Imports
# =============================================================================
from botragram.enums import Interval, PositionSide
from botragram.indicators.price_action.candlesticks import (
    detect_all_candlestick_patterns,
    detect_doji,
    detect_engulfing,
    detect_harami,
    detect_marubozu,
    detect_piercing_or_cloud,
    detect_pinbar,
    detect_star,
    detect_three_inside,
    detect_three_soldiers_or_crows,
    detect_tweezers,
)
from botragram.models import Candle


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
        interval=Interval.M15,
        open_time=base_time,
        close_time=base_time + timedelta(minutes=15),
        open_price=Decimal(open_price),
        high_price=Decimal(high_price),
        low_price=Decimal(low_price),
        close_price=Decimal(close_price),
        volume=Decimal(volume),
    )


def test_detect_bullish_pinbar_hammer_success() -> None:
    """Detect a valid bullish pinbar with long lower wick and high close."""
    # Open: 100, High: 101, Low: 90, Close: 100.5
    # Total range = 11, Lower wick = min(100, 100.5) - 90 = 10 (90.9% of range)
    # Upper wick = 101 - 100.5 = 0.5 (4.5% of range)
    candle = _make_candle(
        open_price="100.0",
        high_price="101.0",
        low_price="90.0",
        close_price="100.5",
    )
    result = detect_pinbar(candle=candle)

    assert result.matched
    assert result.side is PositionSide.LONG
    assert result.pattern_name == "bullish_pinbar"
    assert result.rejection_level == Decimal("90.0")
    assert result.wick_ratio > Decimal("0.80")


def test_detect_bearish_pinbar_shooting_star_success() -> None:
    """Detect a valid bearish pinbar with long upper wick and low close."""
    # Open: 100, High: 115, Low: 99.5, Close: 99.8
    # Total range = 15.5, Upper wick = 115 - 100 = 15 (96.7% of range)
    # Lower wick = 99.8 - 99.5 = 0.3 (< 2% of range)
    candle = _make_candle(
        open_price="100.0",
        high_price="115.0",
        low_price="99.5",
        close_price="99.8",
    )
    result = detect_pinbar(candle=candle)

    assert result.matched
    assert result.side is PositionSide.SHORT
    assert result.pattern_name == "bearish_pinbar"
    assert result.rejection_level == Decimal("115.0")
    assert result.wick_ratio > Decimal("0.80")


def test_detect_pinbar_rejection_when_symmetric_doji() -> None:
    """Reject symmetric candles or dojis without clear directional rejection."""
    # Symmetric spinning top
    candle = _make_candle(
        open_price="100.0",
        high_price="110.0",
        low_price="90.0",
        close_price="100.1",
    )
    result = detect_pinbar(candle=candle)

    assert not result.matched
    assert result.side is None
    assert result.pattern_name == "none"


def test_detect_pinbar_zero_range_safely() -> None:
    """Handle flat zero-range candle without division by zero error."""
    candle = _make_candle(
        open_price="100.0",
        high_price="100.0",
        low_price="100.0",
        close_price="100.0",
    )
    result = detect_pinbar(candle=candle)

    assert not result.matched
    assert result.side is None


def test_detect_bullish_engulfing_success() -> None:
    """Detect a valid bullish engulfing pattern exceeding previous body."""
    prev = _make_candle(
        open_price="105.0",
        high_price="106.0",
        low_price="99.0",
        close_price="100.0",  # Red body: 5.0
        minutes_offset=0,
    )
    curr = _make_candle(
        open_price="99.5",
        high_price="108.0",
        low_price="99.0",
        close_price="106.5",  # Green body: 7.0 (1.4x of prev)
        minutes_offset=15,
    )
    result = detect_engulfing(prev_candle=prev, curr_candle=curr)

    assert result.matched
    assert result.side is PositionSide.LONG
    assert result.pattern_name == "bullish_engulfing"
    assert result.rejection_level == Decimal("99.0")


def test_detect_bearish_engulfing_success() -> None:
    """Detect a valid bearish engulfing pattern exceeding previous body."""
    prev = _make_candle(
        open_price="100.0",
        high_price="105.5",
        low_price="99.5",
        close_price="105.0",  # Green body: 5.0
        minutes_offset=0,
    )
    curr = _make_candle(
        open_price="105.5",
        high_price="106.0",
        low_price="97.0",
        close_price="98.0",  # Red body: 7.5 (1.5x of prev)
        minutes_offset=15,
    )
    result = detect_engulfing(prev_candle=prev, curr_candle=curr)

    assert result.matched
    assert result.side is PositionSide.SHORT
    assert result.pattern_name == "bearish_engulfing"
    assert result.rejection_level == Decimal("106.0")


def test_detect_engulfing_rejects_same_color_candles() -> None:
    """Reject engulfing when both candles share the same direction."""
    prev = _make_candle(
        open_price="100.0",
        high_price="103.0",
        low_price="99.0",
        close_price="102.0",  # Green
        minutes_offset=0,
    )
    curr = _make_candle(
        open_price="102.0",
        high_price="106.0",
        low_price="101.0",
        close_price="105.0",  # Also green
        minutes_offset=15,
    )
    result = detect_engulfing(prev_candle=prev, curr_candle=curr)

    assert not result.matched
    assert result.side is None


def test_detect_morning_star_success() -> None:
    """Detect a valid 3-candle Morning Star bullish reversal."""
    c1 = _make_candle(
        open_price="110.0",
        high_price="111.0",
        low_price="99.5",
        close_price="100.0",  # Strong red body = 10, range = 11.5
        minutes_offset=0,
    )
    c2 = _make_candle(
        open_price="99.0",
        high_price="100.0",
        low_price="97.0",  # Lower low probe (97.0 <= 99.5)
        close_price="99.5",  # Small indecision star body = 0.5 (< 35% of 10)
        minutes_offset=15,
    )
    c3 = _make_candle(
        open_price="99.5",
        high_price="107.0",
        low_price="99.0",
        close_price="106.0",  # Strong green: penetrates > 50% into c1 body (106 >= 105)
        minutes_offset=30,
    )
    result = detect_star(
        first_candle=c1,
        second_candle=c2,
        third_candle=c3,
    )

    assert result.matched
    assert result.side is PositionSide.LONG
    assert result.pattern_name == "morning_star"
    assert result.rejection_level == Decimal("97.0")
    assert result.body_ratio > Decimal("0.70")


def test_detect_evening_star_success() -> None:
    """Detect a valid 3-candle Evening Star bearish reversal."""
    c1 = _make_candle(
        open_price="100.0",
        high_price="110.5",
        low_price="99.0",
        close_price="110.0",  # Strong green body = 10, range = 11.5
        minutes_offset=0,
    )
    c2 = _make_candle(
        open_price="111.0",
        high_price="113.0",  # Higher high probe (113.0 >= 110.5)
        low_price="110.5",
        close_price="111.5",  # Small star body = 0.5 (< 35% of 10)
        minutes_offset=15,
    )
    c3 = _make_candle(
        open_price="111.0",
        high_price="111.5",
        low_price="103.0",
        close_price="104.0",  # Strong red: penetrates > 50% into c1 body (104 <= 105)
        minutes_offset=30,
    )
    result = detect_star(
        first_candle=c1,
        second_candle=c2,
        third_candle=c3,
    )

    assert result.matched
    assert result.side is PositionSide.SHORT
    assert result.pattern_name == "evening_star"
    assert result.rejection_level == Decimal("113.0")
    assert result.body_ratio > Decimal("0.70")


def test_detect_star_rejects_insufficient_penetration() -> None:
    """Reject star pattern when third candle fails to penetrate 50% of first body."""
    c1 = _make_candle(
        open_price="110.0",
        high_price="111.0",
        low_price="99.5",
        close_price="100.0",  # Red body = 10
        minutes_offset=0,
    )
    c2 = _make_candle(
        open_price="99.0",
        high_price="100.0",
        low_price="97.0",
        close_price="99.5",
        minutes_offset=15,
    )
    c3 = _make_candle(
        open_price="99.5",
        high_price="103.0",
        low_price="99.0",
        close_price="102.0",  # Only reaches 102 (needs >= 105)
        minutes_offset=30,
    )
    result = detect_star(
        first_candle=c1,
        second_candle=c2,
        third_candle=c3,
    )

    assert not result.matched
    assert result.side is None


def test_detect_star_rejects_large_middle_body() -> None:
    """Reject star pattern when middle star body is too large."""
    c1 = _make_candle(
        open_price="110.0",
        high_price="111.0",
        low_price="99.5",
        close_price="100.0",  # Red body = 10
        minutes_offset=0,
    )
    c2 = _make_candle(
        open_price="95.0",
        high_price="101.0",
        low_price="94.0",
        close_price="100.0",  # Body = 5 (50% of 10 > max 35%)
        minutes_offset=15,
    )
    c3 = _make_candle(
        open_price="100.0",
        high_price="107.0",
        low_price="99.0",
        close_price="106.0",
        minutes_offset=30,
    )
    result = detect_star(
        first_candle=c1,
        second_candle=c2,
        third_candle=c3,
    )

    assert not result.matched
    assert result.side is None


def test_detect_star_zero_range_safely() -> None:
    """Handle flat zero range candles gracefully without division error."""
    flat = _make_candle(
        open_price="100.0",
        high_price="100.0",
        low_price="100.0",
        close_price="100.0",
        minutes_offset=0,
    )
    result = detect_star(
        first_candle=flat,
        second_candle=flat,
        third_candle=flat,
    )

    assert not result.matched
    assert result.side is None


def test_detect_marubozu_bullish_and_bearish() -> None:
    """Detect full-bodied marubozu candles with negligible wicks."""
    bull_maru = _make_candle(
        open_price="100.0",
        high_price="110.0",
        low_price="99.9",
        close_price="109.8",
    )
    res_bull = detect_marubozu(candle=bull_maru)
    assert res_bull.matched
    assert res_bull.side is PositionSide.LONG
    assert res_bull.pattern_name == "bullish_marubozu"

    bear_maru = _make_candle(
        open_price="110.0",
        high_price="110.1",
        low_price="100.0",
        close_price="100.2",
    )
    res_bear = detect_marubozu(candle=bear_maru)
    assert res_bear.matched
    assert res_bear.side is PositionSide.SHORT
    assert res_bear.pattern_name == "bearish_marubozu"

    normal_candle = _make_candle(
        open_price="100.0",
        high_price="120.0",
        low_price="80.0",
        close_price="105.0",
    )
    res_none = detect_marubozu(candle=normal_candle)
    assert not res_none.matched


def test_detect_doji_types() -> None:
    """Detect Dragonfly, Gravestone, and Neutral Doji."""
    dragonfly = _make_candle(
        open_price="100.0",
        high_price="100.2",
        low_price="90.0",
        close_price="100.1",
    )
    res_df = detect_doji(candle=dragonfly)
    assert res_df.matched
    assert res_df.side is PositionSide.LONG
    assert res_df.pattern_name == "dragonfly_doji"

    gravestone = _make_candle(
        open_price="90.0",
        high_price="100.0",
        low_price="89.8",
        close_price="90.1",
    )
    res_gs = detect_doji(candle=gravestone)
    assert res_gs.matched
    assert res_gs.side is PositionSide.SHORT
    assert res_gs.pattern_name == "gravestone_doji"

    neutral = _make_candle(
        open_price="100.0",
        high_price="105.0",
        low_price="95.0",
        close_price="100.1",
    )
    res_neutral = detect_doji(candle=neutral)
    assert res_neutral.matched
    assert res_neutral.side is None
    assert res_neutral.pattern_name == "neutral_doji"


def test_detect_piercing_and_dark_cloud() -> None:
    """Detect Piercing Line (bullish) and Dark Cloud Cover (bearish)."""
    # Piercing line: c1 red, c2 opens lower and closes > 50% into c1 body
    c1 = _make_candle(
        open_price="110.0",
        high_price="111.0",
        low_price="99.0",
        close_price="100.0",
        minutes_offset=0,
    )
    c2 = _make_candle(
        open_price="98.0",
        high_price="108.0",
        low_price="97.0",
        close_price="106.0",  # midpoint = 105, 106 > 105
        minutes_offset=15,
    )
    res_piercing = detect_piercing_or_cloud(prev_candle=c1, curr_candle=c2)
    assert res_piercing.matched
    assert res_piercing.side is PositionSide.LONG
    assert res_piercing.pattern_name == "piercing_line"

    # Dark cloud cover: c1 green, c2 opens higher and closes < 50% into c1 body
    d1 = _make_candle(
        open_price="100.0",
        high_price="111.0",
        low_price="99.0",
        close_price="110.0",
        minutes_offset=0,
    )
    d2 = _make_candle(
        open_price="112.0",
        high_price="113.0",
        low_price="102.0",
        close_price="104.0",  # midpoint = 105, 104 < 105
        minutes_offset=15,
    )
    res_cloud = detect_piercing_or_cloud(prev_candle=d1, curr_candle=d2)
    assert res_cloud.matched
    assert res_cloud.side is PositionSide.SHORT
    assert res_cloud.pattern_name == "dark_cloud_cover"


def test_detect_harami() -> None:
    """Detect Bullish Harami and Bearish Harami."""
    # Bullish Harami: c1 large red, c2 small green inside c1
    c1 = _make_candle(
        open_price="120.0",
        high_price="121.0",
        low_price="99.0",
        close_price="100.0",
        minutes_offset=0,
    )
    c2 = _make_candle(
        open_price="105.0",
        high_price="112.0",
        low_price="104.0",
        close_price="110.0",
        minutes_offset=15,
    )
    res_bull = detect_harami(prev_candle=c1, curr_candle=c2)
    assert res_bull.matched
    assert res_bull.side is PositionSide.LONG
    assert res_bull.pattern_name == "bullish_harami"

    # Bearish Harami: c1 large green, c2 small red inside c1
    d1 = _make_candle(
        open_price="100.0",
        high_price="121.0",
        low_price="99.0",
        close_price="120.0",
        minutes_offset=0,
    )
    d2 = _make_candle(
        open_price="115.0",
        high_price="116.0",
        low_price="108.0",
        close_price="110.0",
        minutes_offset=15,
    )
    res_bear = detect_harami(prev_candle=d1, curr_candle=d2)
    assert res_bear.matched
    assert res_bear.side is PositionSide.SHORT
    assert res_bear.pattern_name == "bearish_harami"


def test_detect_tweezers() -> None:
    """Detect Tweezer Bottom and Tweezer Top."""
    # Tweezer bottom: identical lows
    c1 = _make_candle(
        open_price="110.0",
        high_price="112.0",
        low_price="100.0",
        close_price="102.0",
        minutes_offset=0,
    )
    c2 = _make_candle(
        open_price="102.0",
        high_price="110.0",
        low_price="100.0",
        close_price="108.0",
        minutes_offset=15,
    )
    res_bottom = detect_tweezers(prev_candle=c1, curr_candle=c2)
    assert res_bottom.matched
    assert res_bottom.side is PositionSide.LONG
    assert res_bottom.pattern_name == "tweezer_bottom"

    # Tweezer top: identical highs
    d1 = _make_candle(
        open_price="100.0",
        high_price="115.0",
        low_price="98.0",
        close_price="112.0",
        minutes_offset=0,
    )
    d2 = _make_candle(
        open_price="112.0",
        high_price="115.0",
        low_price="102.0",
        close_price="105.0",
        minutes_offset=15,
    )
    res_top = detect_tweezers(prev_candle=d1, curr_candle=d2)
    assert res_top.matched
    assert res_top.side is PositionSide.SHORT
    assert res_top.pattern_name == "tweezer_top"


def test_detect_three_soldiers_and_crows() -> None:
    """Detect Three White Soldiers and Three Black Crows."""
    # Three white soldiers: consecutive rising green candles
    c1 = _make_candle(
        open_price="100.0",
        high_price="106.0",
        low_price="99.0",
        close_price="105.0",
        minutes_offset=0,
    )
    c2 = _make_candle(
        open_price="104.0",
        high_price="111.0",
        low_price="103.0",
        close_price="110.0",
        minutes_offset=15,
    )
    c3 = _make_candle(
        open_price="109.0",
        high_price="116.0",
        low_price="108.0",
        close_price="115.0",
        minutes_offset=30,
    )
    res_soldiers = detect_three_soldiers_or_crows(
        first_candle=c1, second_candle=c2, third_candle=c3
    )
    assert res_soldiers.matched
    assert res_soldiers.side is PositionSide.LONG
    assert res_soldiers.pattern_name == "three_white_soldiers"

    # Three black crows: consecutive falling red candles
    d1 = _make_candle(
        open_price="115.0",
        high_price="116.0",
        low_price="109.0",
        close_price="110.0",
        minutes_offset=0,
    )
    d2 = _make_candle(
        open_price="111.0",
        high_price="112.0",
        low_price="104.0",
        close_price="105.0",
        minutes_offset=15,
    )
    d3 = _make_candle(
        open_price="106.0",
        high_price="107.0",
        low_price="99.0",
        close_price="100.0",
        minutes_offset=30,
    )
    res_crows = detect_three_soldiers_or_crows(
        first_candle=d1, second_candle=d2, third_candle=d3
    )
    assert res_crows.matched
    assert res_crows.side is PositionSide.SHORT
    assert res_crows.pattern_name == "three_black_crows"


def test_detect_three_inside() -> None:
    """Detect Three Inside Up and Three Inside Down."""
    # Three Inside Up: c1 red, c2 harami, c3 breaks above c1 open
    c1 = _make_candle(
        open_price="110.0",
        high_price="111.0",
        low_price="99.0",
        close_price="100.0",
        minutes_offset=0,
    )
    c2 = _make_candle(
        open_price="103.0",
        high_price="108.0",
        low_price="102.0",
        close_price="107.0",
        minutes_offset=15,
    )
    c3 = _make_candle(
        open_price="107.0",
        high_price="115.0",
        low_price="106.0",
        close_price="112.0",
        minutes_offset=30,
    )
    res_up = detect_three_inside(first_candle=c1, second_candle=c2, third_candle=c3)
    assert res_up.matched
    assert res_up.side is PositionSide.LONG
    assert res_up.pattern_name == "three_inside_up"


def test_detect_all_candlestick_patterns() -> None:
    """Verify unified pattern scanner returns all active matches."""
    c1 = _make_candle(
        open_price="110.0",
        high_price="111.0",
        low_price="99.0",
        close_price="100.0",
        minutes_offset=0,
    )
    c2 = _make_candle(
        open_price="103.0",
        high_price="108.0",
        low_price="102.0",
        close_price="107.0",
        minutes_offset=15,
    )
    c3 = _make_candle(
        open_price="107.0",
        high_price="115.0",
        low_price="106.0",
        close_price="112.0",
        minutes_offset=30,
    )
    matches = detect_all_candlestick_patterns(candles=(c1, c2, c3))
    assert len(matches) >= 1
    pattern_names = [m.pattern_name for m in matches]
    assert "three_inside_up" in pattern_names


def test_detect_pinbar_min_range_rejection() -> None:
    """Reject pinbar when candle range is below absolute min_range."""
    candle = _make_candle(
        open_price="100.0",
        high_price="100.1",
        low_price="99.0",
        close_price="100.05",
    )
    # Range is 1.1, lower wick is 1.0 (90.9% of range)
    # Pass without min_range
    assert detect_pinbar(candle=candle).matched

    # Reject with min_range = 2.0
    result = detect_pinbar(candle=candle, min_range=Decimal("2.0"))
    assert not result.matched


def test_detect_pinbar_min_range_atr_scaling() -> None:
    """Validate pinbar rejection and acceptance based on ATR volatility scaling."""
    candle = _make_candle(
        open_price="100.0",
        high_price="101.0",
        low_price="90.0",
        close_price="100.5",
    )
    # Range is 11.0
    atr = Decimal("15.0")
    # With min_range_atr = 1.0, required range is 15.0 -> should reject
    res_reject = detect_pinbar(
        candle=candle,
        min_range_atr=Decimal("1.0"),
        atr=atr,
    )
    assert not res_reject.matched

    # With min_range_atr = 0.5, required range is 7.5 -> should pass
    res_pass = detect_pinbar(
        candle=candle,
        min_range_atr=Decimal("0.5"),
        atr=atr,
    )
    assert res_pass.matched
    assert res_pass.side is PositionSide.LONG


def test_detect_engulfing_min_body_rejection() -> None:
    """Reject engulfing pattern when current body is below absolute min_body."""
    prev = _make_candle(
        open_price="100.2",
        high_price="100.3",
        low_price="99.9",
        close_price="100.0",  # Body = 0.2
    )
    curr = _make_candle(
        open_price="99.95",
        high_price="100.35",
        low_price="99.9",
        close_price="100.25",  # Body = 0.3 >= 1.05 * 0.2
    )
    assert detect_engulfing(prev_candle=prev, curr_candle=curr).matched

    # Reject with min_body = 0.5
    result = detect_engulfing(
        prev_candle=prev, curr_candle=curr, min_body=Decimal("0.5")
    )
    assert not result.matched


def test_detect_engulfing_min_body_atr_scaling() -> None:
    """Validate engulfing rejection and acceptance based on ATR volatility scaling."""
    prev = _make_candle(
        open_price="105.0",
        high_price="106.0",
        low_price="99.0",
        close_price="100.0",  # Body = 5.0
    )
    curr = _make_candle(
        open_price="99.5",
        high_price="108.0",
        low_price="99.0",
        close_price="107.0",  # Body = 7.5
    )
    atr = Decimal("10.0")
    # min_body_atr = 0.9 -> required = 9.0 -> 7.5 < 9.0 -> reject
    res_reject = detect_engulfing(
        prev_candle=prev,
        curr_candle=curr,
        min_body_atr=Decimal("0.9"),
        atr=atr,
    )
    assert not res_reject.matched

    # min_body_atr = 0.7 -> required = 7.0 -> 7.5 >= 7.0 -> pass
    res_pass = detect_engulfing(
        prev_candle=prev,
        curr_candle=curr,
        min_body_atr=Decimal("0.7"),
        atr=atr,
    )
    assert res_pass.matched
    assert res_pass.side is PositionSide.LONG


def test_detect_engulfing_min_body_range_ratio() -> None:
    """Reject engulfing pattern when body does not dominate candle range."""
    prev = _make_candle(
        open_price="102.0",
        high_price="102.5",
        low_price="99.5",
        close_price="100.0",  # Body = 2.0
    )
    curr = _make_candle(
        open_price="99.8",
        high_price="120.0",  # Massive upper wick
        low_price="80.0",  # Massive lower wick
        close_price="102.2",  # Body = 2.4, Range = 40.0, Body ratio = 0.06
    )
    # Without min_body_range_ratio, engulfing matches because 2.4 >= 1.05 * 2.0
    assert detect_engulfing(prev_candle=prev, curr_candle=curr).matched

    # With min_body_range_ratio = 0.40, rejects because 0.06 < 0.40
    res_reject = detect_engulfing(
        prev_candle=prev,
        curr_candle=curr,
        min_body_range_ratio=Decimal("0.40"),
    )
    assert not res_reject.matched
