"""
Botragram

Description:
    Supertrend indicator.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.indicators.volatility.atr import calculate_atr

__all__ = [
    "SupertrendResult",
    "calculate_supertrend",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_TWO = Decimal("2")
_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# Result Models
# =============================================================================
@dataclass(
    slots=True,
    frozen=True,
)
class SupertrendResult:
    """Calculated Supertrend values."""

    values: tuple[Decimal, ...]
    is_uptrend: tuple[bool, ...]


# =============================================================================
# Indicator Functions
# =============================================================================
def _calculate_basic_bands(
    aligned_highs: Sequence[Decimal],
    aligned_lows: Sequence[Decimal],
    atr_values: Sequence[Decimal],
    multiplier: Decimal,
) -> tuple[list[Decimal], list[Decimal]]:
    """Calculate basic upper and lower bands."""
    basic_upper_bands: list[Decimal] = []
    basic_lower_bands: list[Decimal] = []

    for high, low, atr in zip(
        aligned_highs,
        aligned_lows,
        atr_values,
        strict=True,
    ):
        midpoint = (high + low) / _DECIMAL_TWO
        distance = multiplier * atr

        basic_upper_bands.append(midpoint + distance)
        basic_lower_bands.append(midpoint - distance)

    return basic_upper_bands, basic_lower_bands


def _calculate_final_bands(
    previous_upper: Decimal,
    previous_lower: Decimal,
    previous_close: Decimal,
    current_basic_upper: Decimal,
    current_basic_lower: Decimal,
) -> tuple[Decimal, Decimal]:
    """Calculate final upper and lower bands for current index."""
    current_final_upper = (
        current_basic_upper
        if (current_basic_upper < previous_upper or previous_close > previous_upper)
        else previous_upper
    )

    current_final_lower = (
        current_basic_lower
        if (current_basic_lower > previous_lower or previous_close < previous_lower)
        else previous_lower
    )

    return current_final_upper, current_final_lower


def _calculate_supertrend_and_trend(
    previous_supertrend: Decimal,
    previous_upper: Decimal,
    current_close: Decimal,
    current_final_upper: Decimal,
    current_final_lower: Decimal,
) -> tuple[Decimal, bool]:
    """Calculate current supertrend value and trend direction."""
    if previous_supertrend == previous_upper:
        if current_close <= current_final_upper:
            return current_final_upper, False
        else:
            return current_final_lower, True
    else:
        if current_close >= current_final_lower:
            return current_final_lower, True
        else:
            return current_final_upper, False


def calculate_supertrend(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    closes: Sequence[Decimal],
    *,
    period: int = 10,
    multiplier: Decimal = Decimal("3"),
) -> SupertrendResult:
    """Calculate Supertrend values.

    Args:
        highs: Ordered high prices from oldest to newest.
        lows: Ordered low prices from oldest to newest.
        closes: Ordered close prices from oldest to newest.
        period: ATR lookback period.
        multiplier: ATR band multiplier.

    Returns:
        Supertrend values and trend directions beginning from the first
        complete ATR period.

    Raises:
        ValueError: If periods, multiplier, or price sequences are invalid.
    """
    if period <= 0:
        raise ValueError("Supertrend period must be greater than zero")

    if multiplier <= _DECIMAL_ZERO:
        raise ValueError("Supertrend multiplier must be greater than zero")

    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("Supertrend price sequences must have equal lengths")

    if len(closes) < period:
        raise ValueError("Supertrend requires at least as many values as its period")

    atr_values = calculate_atr(
        highs,
        lows,
        closes,
        period=period,
    )

    offset = period - 1

    aligned_highs = highs[offset:]
    aligned_lows = lows[offset:]
    aligned_closes = closes[offset:]

    basic_upper_bands, basic_lower_bands = _calculate_basic_bands(
        aligned_highs,
        aligned_lows,
        atr_values,
        multiplier,
    )

    final_upper_bands: list[Decimal] = [basic_upper_bands[0]]
    final_lower_bands: list[Decimal] = [basic_lower_bands[0]]

    supertrend_values: list[Decimal] = []
    trend_values: list[bool] = []

    initial_uptrend = aligned_closes[0] >= basic_lower_bands[0]

    supertrend_values.append(
        basic_lower_bands[0] if initial_uptrend else basic_upper_bands[0]
    )
    trend_values.append(initial_uptrend)

    for index in range(1, len(atr_values)):
        previous_close = aligned_closes[index - 1]
        current_close = aligned_closes[index]

        previous_upper = final_upper_bands[index - 1]
        previous_lower = final_lower_bands[index - 1]

        current_basic_upper = basic_upper_bands[index]
        current_basic_lower = basic_lower_bands[index]

        current_final_upper, current_final_lower = _calculate_final_bands(
            previous_upper,
            previous_lower,
            previous_close,
            current_basic_upper,
            current_basic_lower,
        )

        final_upper_bands.append(current_final_upper)
        final_lower_bands.append(current_final_lower)

        previous_supertrend = supertrend_values[index - 1]

        current_supertrend, current_uptrend = _calculate_supertrend_and_trend(
            previous_supertrend,
            previous_upper,
            current_close,
            current_final_upper,
            current_final_lower,
        )

        supertrend_values.append(current_supertrend)
        trend_values.append(current_uptrend)

    return SupertrendResult(
        values=tuple(supertrend_values),
        is_uptrend=tuple(trend_values),
    )
