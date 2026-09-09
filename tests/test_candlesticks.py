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
    detect_engulfing,
    detect_pinbar,
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
