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
    "detect_engulfing",
    "detect_pinbar",
]

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DEFAULT_MIN_WICK_RATIO: Final[Decimal] = Decimal("0.60")
_DEFAULT_MAX_OPPOSITE_WICK_RATIO: Final[Decimal] = Decimal("0.20")
_DEFAULT_MIN_ENGULFING_BODY_RATIO: Final[Decimal] = Decimal("1.05")
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
        )

    return CandlestickMatch(
        matched=False,
        side=None,
        pattern_name="none",
        rejection_level=_DECIMAL_ZERO,
        body_ratio=curr_body_ratio,
        wick_ratio=_DECIMAL_ZERO,
    )
