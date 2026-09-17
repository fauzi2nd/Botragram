"""
Botragram

Description:
    Mathematical candlestick pattern detection indicators.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import PositionSide
from botragram.models import Candle

__all__ = [
    "CandlestickMatch",
    "detect_all_candlestick_patterns",
    "detect_doji",
    "detect_engulfing",
    "detect_harami",
    "detect_marubozu",
    "detect_piercing_or_cloud",
    "detect_pinbar",
    "detect_star",
    "detect_three_inside",
    "detect_three_soldiers_or_crows",
    "detect_tweezers",
]

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DEFAULT_MIN_WICK_RATIO: Final[Decimal] = Decimal("0.60")
_DEFAULT_MAX_OPPOSITE_WICK_RATIO: Final[Decimal] = Decimal("0.20")
_DEFAULT_MIN_ENGULFING_BODY_RATIO: Final[Decimal] = Decimal("1.05")
_DEFAULT_MIN_STAR_FIRST_BODY_RATIO: Final[Decimal] = Decimal("0.50")
_DEFAULT_MAX_STAR_MIDDLE_BODY_RATIO: Final[Decimal] = Decimal("0.35")
_DEFAULT_MIN_STAR_PENETRATION_RATIO: Final[Decimal] = Decimal("0.50")
_DEFAULT_MIN_MARUBOZU_BODY_RATIO: Final[Decimal] = Decimal("0.85")
_DEFAULT_MAX_DOJI_BODY_RATIO: Final[Decimal] = Decimal("0.10")
_DEFAULT_MIN_PIERCING_PENETRATION_RATIO: Final[Decimal] = Decimal("0.50")
_DEFAULT_MAX_TWEEZER_DIFF_PCT: Final[Decimal] = Decimal("0.001")
_MIN_LOCATION_RATIO: Final[Decimal] = Decimal("0.60")


# =============================================================================
# Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class CandlestickMatch:
    """Result of a candlestick pattern recognition evaluation."""

    matched: bool
    side: PositionSide | None
    pattern_name: str
    rejection_level: Decimal
    body_ratio: Decimal
    wick_ratio: Decimal
    pattern_ratio: Decimal = _DECIMAL_ZERO


# =============================================================================
# Detection Functions
# =============================================================================
def detect_pinbar(
    *,
    candle: Candle,
    min_wick_ratio: Decimal = _DEFAULT_MIN_WICK_RATIO,
    max_opposite_wick_ratio: Decimal = _DEFAULT_MAX_OPPOSITE_WICK_RATIO,
) -> CandlestickMatch:
    """Detect a bullish hammer or bearish shooting-star pinbar rejection.

    Args:
        candle: Candlestick to evaluate.
        min_wick_ratio: Minimum ratio of rejection wick to total candle range.
        max_opposite_wick_ratio: Maximum allowable opposite wick ratio.

    Returns:
        A CandlestickMatch describing the detected pattern, if any.
    """
    total_range = candle.high_price - candle.low_price
    if total_range <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    body = abs(candle.close_price - candle.open_price)
    body_ratio = body / total_range
    upper_wick = candle.high_price - max(candle.open_price, candle.close_price)
    lower_wick = min(candle.open_price, candle.close_price) - candle.low_price

    lower_wick_ratio = lower_wick / total_range
    upper_wick_ratio = upper_wick / total_range

    # Bullish Pinbar (Hammer / Low Rejection)
    if (
        lower_wick_ratio >= min_wick_ratio
        and upper_wick_ratio <= max_opposite_wick_ratio
        and ((candle.close_price - candle.low_price) / total_range)
        >= _MIN_LOCATION_RATIO
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.LONG,
            pattern_name="bullish_pinbar",
            rejection_level=candle.low_price,
            body_ratio=body_ratio,
            wick_ratio=lower_wick_ratio,
            pattern_ratio=lower_wick_ratio,
        )

    # Bearish Pinbar (Shooting Star / High Rejection)
    if (
        upper_wick_ratio >= min_wick_ratio
        and lower_wick_ratio <= max_opposite_wick_ratio
        and ((candle.high_price - candle.close_price) / total_range)
        >= _MIN_LOCATION_RATIO
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.SHORT,
            pattern_name="bearish_pinbar",
            rejection_level=candle.high_price,
            body_ratio=body_ratio,
            wick_ratio=upper_wick_ratio,
            pattern_ratio=upper_wick_ratio,
        )

    return CandlestickMatch(
        matched=False,
        side=None,
        pattern_name="none",
        rejection_level=_DECIMAL_ZERO,
        body_ratio=body_ratio,
        wick_ratio=max(lower_wick_ratio, upper_wick_ratio),
    )


def detect_engulfing(
    *,
    prev_candle: Candle,
    curr_candle: Candle,
    min_body_ratio: Decimal = _DEFAULT_MIN_ENGULFING_BODY_RATIO,
) -> CandlestickMatch:
    """Detect a bullish or bearish engulfing candlestick pattern.

    Args:
        prev_candle: Preceding closed candlestick.
        curr_candle: Current evaluated closed candlestick.
        min_body_ratio: Multiplier by which current body must exceed previous.

    Returns:
        A CandlestickMatch describing the detected pattern, if any.
    """
    curr_range = curr_candle.high_price - curr_candle.low_price
    if curr_range <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    prev_body = abs(prev_candle.close_price - prev_candle.open_price)
    curr_body = abs(curr_candle.close_price - curr_candle.open_price)
    curr_body_ratio = curr_body / curr_range

    if prev_body <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=curr_body_ratio,
            wick_ratio=_DECIMAL_ZERO,
        )

    # Bullish Engulfing: previous red, current green, current body engulfs
    if (
        prev_candle.close_price < prev_candle.open_price
        and curr_candle.close_price > curr_candle.open_price
        and curr_candle.close_price >= prev_candle.open_price
        and curr_candle.open_price <= prev_candle.close_price
        and curr_body >= (min_body_ratio * prev_body)
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.LONG,
            pattern_name="bullish_engulfing",
            rejection_level=min(prev_candle.low_price, curr_candle.low_price),
            body_ratio=curr_body_ratio,
            wick_ratio=curr_body / prev_body,
            pattern_ratio=curr_body / prev_body,
        )

    # Bearish Engulfing: previous green, current red, current body engulfs
    if (
        prev_candle.close_price > prev_candle.open_price
        and curr_candle.close_price < curr_candle.open_price
        and curr_candle.open_price >= prev_candle.close_price
        and curr_candle.close_price <= prev_candle.open_price
        and curr_body >= (min_body_ratio * prev_body)
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.SHORT,
            pattern_name="bearish_engulfing",
            rejection_level=max(prev_candle.high_price, curr_candle.high_price),
            body_ratio=curr_body_ratio,
            wick_ratio=curr_body / prev_body,
            pattern_ratio=curr_body / prev_body,
        )

    return CandlestickMatch(
        matched=False,
        side=None,
        pattern_name="none",
        rejection_level=_DECIMAL_ZERO,
        body_ratio=curr_body_ratio,
        wick_ratio=_DECIMAL_ZERO,
    )


def detect_star(
    *,
    first_candle: Candle,
    second_candle: Candle,
    third_candle: Candle,
    min_first_body_ratio: Decimal = _DEFAULT_MIN_STAR_FIRST_BODY_RATIO,
    max_middle_body_ratio: Decimal = _DEFAULT_MAX_STAR_MIDDLE_BODY_RATIO,
    min_penetration_ratio: Decimal = _DEFAULT_MIN_STAR_PENETRATION_RATIO,
) -> CandlestickMatch:
    """Detect a 3-candle Morning Star (bullish) or Evening Star (bearish) reversal.

    Args:
        first_candle: Preceding trend candlestick.
        second_candle: Middle star (indecision) candlestick.
        third_candle: Current confirmation candlestick.
        min_first_body_ratio: Minimum body-to-range ratio for the first candle.
        max_middle_body_ratio: Maximum allowable middle body relative to first body.
        min_penetration_ratio: Minimum penetration of third candle into first body.

    Returns:
        A CandlestickMatch describing the detected pattern, if any.
    """
    third_range = third_candle.high_price - third_candle.low_price
    if third_range <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    first_range = first_candle.high_price - first_candle.low_price
    if first_range <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    first_body = abs(first_candle.close_price - first_candle.open_price)
    if (first_body / first_range) < min_first_body_ratio:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    second_body = abs(second_candle.close_price - second_candle.open_price)
    if second_body > (max_middle_body_ratio * first_body):
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    third_body = abs(third_candle.close_price - third_candle.open_price)
    third_body_ratio = third_body / third_range

    # Morning Star: 1st red, 2nd small with lower low/probe, 3rd green penetrates >= 50%
    if (
        first_candle.close_price < first_candle.open_price
        and second_candle.low_price <= first_candle.low_price
        and third_candle.close_price > third_candle.open_price
        and third_candle.close_price
        >= (first_candle.close_price + (first_body * min_penetration_ratio))
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.LONG,
            pattern_name="morning_star",
            rejection_level=min(
                first_candle.low_price,
                second_candle.low_price,
                third_candle.low_price,
            ),
            body_ratio=third_body_ratio,
            wick_ratio=third_body / first_body,
            pattern_ratio=third_body / first_body,
        )

    # Evening Star: 1st green, 2nd small with higher high/probe,
    # 3rd red penetrates >= 50% into 1st body.
    if (
        first_candle.close_price > first_candle.open_price
        and second_candle.high_price >= first_candle.high_price
        and third_candle.close_price < third_candle.open_price
        and third_candle.close_price
        <= (first_candle.close_price - (first_body * min_penetration_ratio))
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.SHORT,
            pattern_name="evening_star",
            rejection_level=max(
                first_candle.high_price,
                second_candle.high_price,
                third_candle.high_price,
            ),
            body_ratio=third_body_ratio,
            wick_ratio=third_body / first_body,
            pattern_ratio=third_body / first_body,
        )

    return CandlestickMatch(
        matched=False,
        side=None,
        pattern_name="none",
        rejection_level=_DECIMAL_ZERO,
        body_ratio=third_body_ratio,
        wick_ratio=_DECIMAL_ZERO,
    )


def detect_marubozu(
    *,
    candle: Candle,
    min_body_ratio: Decimal = _DEFAULT_MIN_MARUBOZU_BODY_RATIO,
) -> CandlestickMatch:
    """Detect a bullish or bearish marubozu momentum candlestick."""
    total_range = candle.high_price - candle.low_price
    if total_range <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    body = abs(candle.close_price - candle.open_price)
    body_ratio = body / total_range
    if body_ratio < min_body_ratio:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=body_ratio,
            wick_ratio=_DECIMAL_ZERO,
        )

    if candle.close_price > candle.open_price:
        return CandlestickMatch(
            matched=True,
            side=PositionSide.LONG,
            pattern_name="bullish_marubozu",
            rejection_level=candle.low_price,
            body_ratio=body_ratio,
            wick_ratio=_DECIMAL_ZERO,
            pattern_ratio=body_ratio,
        )

    if candle.close_price < candle.open_price:
        return CandlestickMatch(
            matched=True,
            side=PositionSide.SHORT,
            pattern_name="bearish_marubozu",
            rejection_level=candle.high_price,
            body_ratio=body_ratio,
            wick_ratio=_DECIMAL_ZERO,
            pattern_ratio=body_ratio,
        )

    return CandlestickMatch(
        matched=False,
        side=None,
        pattern_name="none",
        rejection_level=_DECIMAL_ZERO,
        body_ratio=body_ratio,
        wick_ratio=_DECIMAL_ZERO,
    )


def detect_doji(
    *,
    candle: Candle,
    max_body_ratio: Decimal = _DEFAULT_MAX_DOJI_BODY_RATIO,
) -> CandlestickMatch:
    """Detect a neutral, dragonfly (bullish), or gravestone (bearish) doji."""
    total_range = candle.high_price - candle.low_price
    if total_range <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    body = abs(candle.close_price - candle.open_price)
    body_ratio = body / total_range
    if body_ratio > max_body_ratio:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=body_ratio,
            wick_ratio=_DECIMAL_ZERO,
        )

    upper_wick = candle.high_price - max(candle.open_price, candle.close_price)
    lower_wick = min(candle.open_price, candle.close_price) - candle.low_price
    lower_wick_ratio = lower_wick / total_range
    upper_wick_ratio = upper_wick / total_range

    # Dragonfly Doji: long lower shadow, minimal upper shadow -> bullish rejection
    if lower_wick_ratio >= Decimal("0.60") and upper_wick_ratio <= Decimal("0.15"):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.LONG,
            pattern_name="dragonfly_doji",
            rejection_level=candle.low_price,
            body_ratio=body_ratio,
            wick_ratio=lower_wick_ratio,
            pattern_ratio=lower_wick_ratio,
        )

    # Gravestone Doji: long upper shadow, minimal lower shadow -> bearish rejection
    if upper_wick_ratio >= Decimal("0.60") and lower_wick_ratio <= Decimal("0.15"):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.SHORT,
            pattern_name="gravestone_doji",
            rejection_level=candle.high_price,
            body_ratio=body_ratio,
            wick_ratio=upper_wick_ratio,
            pattern_ratio=upper_wick_ratio,
        )

    # Neutral / Long-legged Doji
    return CandlestickMatch(
        matched=True,
        side=None,
        pattern_name="neutral_doji",
        rejection_level=(candle.high_price + candle.low_price) / Decimal("2"),
        body_ratio=body_ratio,
        wick_ratio=max(upper_wick_ratio, lower_wick_ratio),
        pattern_ratio=body_ratio,
    )


def detect_piercing_or_cloud(
    *,
    prev_candle: Candle,
    curr_candle: Candle,
    min_penetration_ratio: Decimal = _DEFAULT_MIN_PIERCING_PENETRATION_RATIO,
) -> CandlestickMatch:
    """Detect Bullish Piercing Line or Bearish Dark Cloud Cover reversal."""
    prev_range = prev_candle.high_price - prev_candle.low_price
    curr_range = curr_candle.high_price - curr_candle.low_price
    if prev_range <= _DECIMAL_ZERO or curr_range <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    prev_body = abs(prev_candle.close_price - prev_candle.open_price)
    curr_body = abs(curr_candle.close_price - curr_candle.open_price)
    if prev_body <= _DECIMAL_ZERO or curr_body <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    prev_midpoint = (prev_candle.open_price + prev_candle.close_price) / Decimal("2")

    # Piercing Line: previous red, current green, opens <= prev close,
    # closes > midpoint but < prev open (non-engulfing)
    if (
        prev_candle.close_price < prev_candle.open_price
        and curr_candle.close_price > curr_candle.open_price
        and curr_candle.open_price <= prev_candle.close_price
        and curr_candle.close_price > prev_midpoint
        and curr_candle.close_price < prev_candle.open_price
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.LONG,
            pattern_name="piercing_line",
            rejection_level=min(prev_candle.low_price, curr_candle.low_price),
            body_ratio=curr_body / curr_range,
            wick_ratio=curr_body / prev_body,
            pattern_ratio=curr_body / prev_body,
        )

    # Dark Cloud Cover: previous green, current red, opens >= prev close,
    # closes < midpoint but > prev open (non-engulfing)
    if (
        prev_candle.close_price > prev_candle.open_price
        and curr_candle.close_price < curr_candle.open_price
        and curr_candle.open_price >= prev_candle.close_price
        and curr_candle.close_price < prev_midpoint
        and curr_candle.close_price > prev_candle.open_price
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.SHORT,
            pattern_name="dark_cloud_cover",
            rejection_level=max(prev_candle.high_price, curr_candle.high_price),
            body_ratio=curr_body / curr_range,
            wick_ratio=curr_body / prev_body,
            pattern_ratio=curr_body / prev_body,
        )

    return CandlestickMatch(
        matched=False,
        side=None,
        pattern_name="none",
        rejection_level=_DECIMAL_ZERO,
        body_ratio=curr_body / curr_range,
        wick_ratio=_DECIMAL_ZERO,
    )


def detect_harami(
    *,
    prev_candle: Candle,
    curr_candle: Candle,
) -> CandlestickMatch:
    """Detect Bullish or Bearish Harami (inside bar) candlestick pattern."""
    prev_range = prev_candle.high_price - prev_candle.low_price
    curr_range = curr_candle.high_price - curr_candle.low_price
    if prev_range <= _DECIMAL_ZERO or curr_range <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    prev_body = abs(prev_candle.close_price - prev_candle.open_price)
    curr_body = abs(curr_candle.close_price - curr_candle.open_price)
    if prev_body <= _DECIMAL_ZERO or curr_body <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    # Bullish Harami: prev red, curr green, curr body contained inside prev body
    if (
        prev_candle.close_price < prev_candle.open_price
        and curr_candle.close_price > curr_candle.open_price
        and curr_candle.open_price >= prev_candle.close_price
        and curr_candle.close_price <= prev_candle.open_price
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.LONG,
            pattern_name="bullish_harami",
            rejection_level=prev_candle.low_price,
            body_ratio=curr_body / curr_range,
            wick_ratio=curr_body / prev_body,
            pattern_ratio=curr_body / prev_body,
        )

    # Bearish Harami: prev green, curr red, curr body contained inside prev body
    if (
        prev_candle.close_price > prev_candle.open_price
        and curr_candle.close_price < curr_candle.open_price
        and curr_candle.open_price <= prev_candle.close_price
        and curr_candle.close_price >= prev_candle.open_price
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.SHORT,
            pattern_name="bearish_harami",
            rejection_level=prev_candle.high_price,
            body_ratio=curr_body / curr_range,
            wick_ratio=curr_body / prev_body,
            pattern_ratio=curr_body / prev_body,
        )

    return CandlestickMatch(
        matched=False,
        side=None,
        pattern_name="none",
        rejection_level=_DECIMAL_ZERO,
        body_ratio=curr_body / curr_range,
        wick_ratio=_DECIMAL_ZERO,
    )


def detect_tweezers(
    *,
    prev_candle: Candle,
    curr_candle: Candle,
    max_diff_pct: Decimal = _DEFAULT_MAX_TWEEZER_DIFF_PCT,
) -> CandlestickMatch:
    """Detect Tweezer Bottom (bullish) or Tweezer Top (bearish) rejection."""
    curr_range = curr_candle.high_price - curr_candle.low_price
    if curr_range <= _DECIMAL_ZERO or curr_candle.close_price <= _DECIMAL_ZERO:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    # Tweezer Bottom: matching lows
    low_diff_pct = (
        abs(curr_candle.low_price - prev_candle.low_price) / curr_candle.close_price
    )
    if (
        low_diff_pct <= max_diff_pct
        and prev_candle.close_price < prev_candle.open_price
        and curr_candle.close_price > curr_candle.open_price
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.LONG,
            pattern_name="tweezer_bottom",
            rejection_level=min(prev_candle.low_price, curr_candle.low_price),
            body_ratio=abs(curr_candle.close_price - curr_candle.open_price)
            / curr_range,
            wick_ratio=low_diff_pct,
            pattern_ratio=Decimal("1") - low_diff_pct,
        )

    # Tweezer Top: matching highs
    high_diff_pct = (
        abs(curr_candle.high_price - prev_candle.high_price) / curr_candle.close_price
    )
    if (
        high_diff_pct <= max_diff_pct
        and prev_candle.close_price > prev_candle.open_price
        and curr_candle.close_price < curr_candle.open_price
    ):
        return CandlestickMatch(
            matched=True,
            side=PositionSide.SHORT,
            pattern_name="tweezer_top",
            rejection_level=max(prev_candle.high_price, curr_candle.high_price),
            body_ratio=abs(curr_candle.close_price - curr_candle.open_price)
            / curr_range,
            wick_ratio=high_diff_pct,
            pattern_ratio=Decimal("1") - high_diff_pct,
        )

    return CandlestickMatch(
        matched=False,
        side=None,
        pattern_name="none",
        rejection_level=_DECIMAL_ZERO,
        body_ratio=_DECIMAL_ZERO,
        wick_ratio=_DECIMAL_ZERO,
    )


def detect_three_soldiers_or_crows(
    *,
    first_candle: Candle,
    second_candle: Candle,
    third_candle: Candle,
) -> CandlestickMatch:
    """Detect Three White Soldiers (bullish) or Three Black Crows (bearish)."""
    # Three White Soldiers
    if (
        first_candle.close_price > first_candle.open_price
        and second_candle.close_price > second_candle.open_price
        and third_candle.close_price > third_candle.open_price
        and first_candle.close_price
        < second_candle.close_price
        < third_candle.close_price
        and first_candle.open_price < second_candle.open_price < third_candle.open_price
        and second_candle.open_price >= first_candle.open_price
        and second_candle.open_price <= first_candle.close_price
        and third_candle.open_price >= second_candle.open_price
        and third_candle.open_price <= second_candle.close_price
    ):
        third_range = third_candle.high_price - third_candle.low_price
        third_body = third_candle.close_price - third_candle.open_price
        b_ratio = (
            third_body / third_range if third_range > _DECIMAL_ZERO else _DECIMAL_ZERO
        )
        return CandlestickMatch(
            matched=True,
            side=PositionSide.LONG,
            pattern_name="three_white_soldiers",
            rejection_level=first_candle.low_price,
            body_ratio=b_ratio,
            wick_ratio=_DECIMAL_ZERO,
            pattern_ratio=Decimal("1"),
        )

    # Three Black Crows
    if (
        first_candle.close_price < first_candle.open_price
        and second_candle.close_price < second_candle.open_price
        and third_candle.close_price < third_candle.open_price
        and first_candle.close_price
        > second_candle.close_price
        > third_candle.close_price
        and first_candle.open_price > second_candle.open_price > third_candle.open_price
        and second_candle.open_price <= first_candle.open_price
        and second_candle.open_price >= first_candle.close_price
        and third_candle.open_price <= second_candle.open_price
        and third_candle.open_price >= second_candle.close_price
    ):
        third_range = third_candle.high_price - third_candle.low_price
        third_body = third_candle.open_price - third_candle.close_price
        b_ratio = (
            third_body / third_range if third_range > _DECIMAL_ZERO else _DECIMAL_ZERO
        )
        return CandlestickMatch(
            matched=True,
            side=PositionSide.SHORT,
            pattern_name="three_black_crows",
            rejection_level=first_candle.high_price,
            body_ratio=b_ratio,
            wick_ratio=_DECIMAL_ZERO,
            pattern_ratio=Decimal("1"),
        )

    return CandlestickMatch(
        matched=False,
        side=None,
        pattern_name="none",
        rejection_level=_DECIMAL_ZERO,
        body_ratio=_DECIMAL_ZERO,
        wick_ratio=_DECIMAL_ZERO,
    )


def detect_three_inside(
    *,
    first_candle: Candle,
    second_candle: Candle,
    third_candle: Candle,
) -> CandlestickMatch:
    """Detect Three Inside Up (bullish) or Three Inside Down (bearish)."""
    harami = detect_harami(prev_candle=first_candle, curr_candle=second_candle)
    if not harami.matched:
        return CandlestickMatch(
            matched=False,
            side=None,
            pattern_name="none",
            rejection_level=_DECIMAL_ZERO,
            body_ratio=_DECIMAL_ZERO,
            wick_ratio=_DECIMAL_ZERO,
        )

    if harami.side is PositionSide.LONG:
        if (
            third_candle.close_price > third_candle.open_price
            and third_candle.close_price > first_candle.open_price
        ):
            return CandlestickMatch(
                matched=True,
                side=PositionSide.LONG,
                pattern_name="three_inside_up",
                rejection_level=first_candle.low_price,
                body_ratio=harami.body_ratio,
                wick_ratio=harami.wick_ratio,
                pattern_ratio=harami.pattern_ratio,
            )

    if harami.side is PositionSide.SHORT:
        if (
            third_candle.close_price < third_candle.open_price
            and third_candle.close_price < first_candle.open_price
        ):
            return CandlestickMatch(
                matched=True,
                side=PositionSide.SHORT,
                pattern_name="three_inside_down",
                rejection_level=first_candle.high_price,
                body_ratio=harami.body_ratio,
                wick_ratio=harami.wick_ratio,
                pattern_ratio=harami.pattern_ratio,
            )

    return CandlestickMatch(
        matched=False,
        side=None,
        pattern_name="none",
        rejection_level=_DECIMAL_ZERO,
        body_ratio=_DECIMAL_ZERO,
        wick_ratio=_DECIMAL_ZERO,
    )


def detect_all_candlestick_patterns(
    *,
    candles: Sequence[Candle],
) -> tuple[CandlestickMatch, ...]:
    """Evaluate trailing candles across all recognized candlestick patterns.

    Scans triple, dual, and single candlestick configurations and returns all
    active pattern matches.
    """
    if not candles:
        return ()

    matches: list[CandlestickMatch] = []
    curr = candles[-1]

    # 1. Triple-Candle Patterns (highest structural weight)
    if len(candles) >= 3:
        first, second, third = candles[-3], candles[-2], candles[-1]
        star_match = detect_star(
            first_candle=first,
            second_candle=second,
            third_candle=third,
        )
        if star_match.matched:
            matches.append(star_match)

        soldiers_match = detect_three_soldiers_or_crows(
            first_candle=first,
            second_candle=second,
            third_candle=third,
        )
        if soldiers_match.matched:
            matches.append(soldiers_match)

        inside_match = detect_three_inside(
            first_candle=first,
            second_candle=second,
            third_candle=third,
        )
        if inside_match.matched:
            matches.append(inside_match)

    # 2. Dual-Candle Patterns
    if len(candles) >= 2:
        prev = candles[-2]
        engulfing_match = detect_engulfing(
            prev_candle=prev,
            curr_candle=curr,
        )
        if engulfing_match.matched:
            matches.append(engulfing_match)

        piercing_match = detect_piercing_or_cloud(
            prev_candle=prev,
            curr_candle=curr,
        )
        if piercing_match.matched:
            matches.append(piercing_match)

        harami_match = detect_harami(
            prev_candle=prev,
            curr_candle=curr,
        )
        if harami_match.matched:
            matches.append(harami_match)

        tweezers_match = detect_tweezers(
            prev_candle=prev,
            curr_candle=curr,
        )
        if tweezers_match.matched:
            matches.append(tweezers_match)

    # 3. Single-Candle Patterns
    pinbar_match = detect_pinbar(candle=curr)
    if pinbar_match.matched:
        matches.append(pinbar_match)

    marubozu_match = detect_marubozu(candle=curr)
    if marubozu_match.matched:
        matches.append(marubozu_match)

    doji_match = detect_doji(candle=curr)
    if doji_match.matched:
        matches.append(doji_match)

    return tuple(matches)
