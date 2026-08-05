"""
Botragram

Description:
    Average Directional Index indicator.

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

__all__ = [
    "ADXResult",
    "calculate_adx",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE_HUNDRED = Decimal("100")


# =============================================================================
# Result Models
# =============================================================================
@dataclass(
    slots=True,
    frozen=True,
)
class ADXResult:
    """Calculated Average Directional Index values."""

    adx: tuple[Decimal, ...]
    plus_di: tuple[Decimal, ...]
    minus_di: tuple[Decimal, ...]


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_adx(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    closes: Sequence[Decimal],
    *,
    period: int = 14,
) -> ADXResult:
    """Calculate Average Directional Index using Wilder smoothing.

    Args:
        highs: Ordered high prices from oldest to newest.
        lows: Ordered low prices from oldest to newest.
        closes: Ordered close prices from oldest to newest.
        period: ADX lookback period.

    Returns:
        ADX, positive directional indicator, and negative directional
        indicator values.

    Raises:
        ValueError: If the period or price sequences are invalid.
    """
    if period <= 0:
        raise ValueError("ADX period must be greater than zero")

    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("ADX price sequences must have equal lengths")

    minimum_values = (period * 2) - 1

    if len(closes) < minimum_values:
        raise ValueError(f"ADX requires at least {minimum_values} values")

    true_ranges: list[Decimal] = []
    plus_dm_values: list[Decimal] = []
    minus_dm_values: list[Decimal] = []

    for index in range(1, len(closes)):
        current_high = highs[index]
        current_low = lows[index]
        previous_high = highs[index - 1]
        previous_low = lows[index - 1]
        previous_close = closes[index - 1]

        upward_move = current_high - previous_high
        downward_move = previous_low - current_low

        plus_dm = (
            upward_move
            if (upward_move > downward_move and upward_move > _DECIMAL_ZERO)
            else _DECIMAL_ZERO
        )

        minus_dm = (
            downward_move
            if (downward_move > upward_move and downward_move > _DECIMAL_ZERO)
            else _DECIMAL_ZERO
        )

        true_range = max(
            current_high - current_low,
            abs(current_high - previous_close),
            abs(current_low - previous_close),
        )

        true_ranges.append(true_range)
        plus_dm_values.append(plus_dm)
        minus_dm_values.append(minus_dm)

    period_decimal = Decimal(period)

    smoothed_true_range = sum(
        true_ranges[:period],
        start=_DECIMAL_ZERO,
    )
    smoothed_plus_dm = sum(
        plus_dm_values[:period],
        start=_DECIMAL_ZERO,
    )
    smoothed_minus_dm = sum(
        minus_dm_values[:period],
        start=_DECIMAL_ZERO,
    )

    plus_di_values: list[Decimal] = []
    minus_di_values: list[Decimal] = []
    dx_values: list[Decimal] = []

    plus_di, minus_di, dx = _calculate_directional_values(
        smoothed_true_range=smoothed_true_range,
        smoothed_plus_dm=smoothed_plus_dm,
        smoothed_minus_dm=smoothed_minus_dm,
    )

    plus_di_values.append(plus_di)
    minus_di_values.append(minus_di)
    dx_values.append(dx)

    for index in range(period, len(true_ranges)):
        smoothed_true_range = (
            smoothed_true_range
            - (smoothed_true_range / period_decimal)
            + true_ranges[index]
        )
        smoothed_plus_dm = (
            smoothed_plus_dm
            - (smoothed_plus_dm / period_decimal)
            + plus_dm_values[index]
        )
        smoothed_minus_dm = (
            smoothed_minus_dm
            - (smoothed_minus_dm / period_decimal)
            + minus_dm_values[index]
        )

        plus_di, minus_di, dx = _calculate_directional_values(
            smoothed_true_range=smoothed_true_range,
            smoothed_plus_dm=smoothed_plus_dm,
            smoothed_minus_dm=smoothed_minus_dm,
        )

        plus_di_values.append(plus_di)
        minus_di_values.append(minus_di)
        dx_values.append(dx)

    initial_adx = (
        sum(
            dx_values[:period],
            start=_DECIMAL_ZERO,
        )
        / period_decimal
    )

    adx_values: list[Decimal] = [
        initial_adx,
    ]
    previous_adx = initial_adx

    for dx in dx_values[period:]:
        current_adx = (
            (previous_adx * (period_decimal - Decimal("1"))) + dx
        ) / period_decimal

        adx_values.append(current_adx)
        previous_adx = current_adx

    aligned_plus_di = tuple(plus_di_values[period - 1 :])
    aligned_minus_di = tuple(minus_di_values[period - 1 :])

    return ADXResult(
        adx=tuple(adx_values),
        plus_di=aligned_plus_di,
        minus_di=aligned_minus_di,
    )


# =============================================================================
# Helper Functions
# =============================================================================
def _calculate_directional_values(
    *,
    smoothed_true_range: Decimal,
    smoothed_plus_dm: Decimal,
    smoothed_minus_dm: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Calculate +DI, -DI, and DX values."""
    if smoothed_true_range == _DECIMAL_ZERO:
        return (
            _DECIMAL_ZERO,
            _DECIMAL_ZERO,
            _DECIMAL_ZERO,
        )

    plus_di = _DECIMAL_ONE_HUNDRED * smoothed_plus_dm / smoothed_true_range
    minus_di = _DECIMAL_ONE_HUNDRED * smoothed_minus_dm / smoothed_true_range

    directional_sum = plus_di + minus_di

    if directional_sum == _DECIMAL_ZERO:
        dx = _DECIMAL_ZERO
    else:
        dx = _DECIMAL_ONE_HUNDRED * abs(plus_di - minus_di) / directional_sum

    return plus_di, minus_di, dx
