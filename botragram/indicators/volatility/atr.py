"""
Botragram

Description:
    Average True Range indicator.

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
from decimal import Decimal

__all__ = [
    "calculate_atr",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_atr(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    closes: Sequence[Decimal],
    *,
    period: int = 14,
) -> tuple[Decimal, ...]:
    """Calculate Average True Range values using Wilder smoothing.

    Args:
        highs: Ordered high prices from oldest to newest.
        lows: Ordered low prices from oldest to newest.
        closes: Ordered close prices from oldest to newest.
        period: ATR lookback period.

    Returns:
        ATR values beginning from the first complete period.

    Raises:
        ValueError: If periods or input sequences are invalid.
    """
    if period <= 0:
        raise ValueError("ATR period must be greater than zero")

    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("ATR price sequences must have equal lengths")

    if len(closes) < period:
        raise ValueError("ATR requires at least as many values as its period")

    if not closes:
        raise ValueError("ATR price sequences must not be empty")

    true_ranges: list[Decimal] = [
        highs[0] - lows[0],
    ]

    for index in range(1, len(closes)):
        high = highs[index]
        low = lows[index]
        previous_close = closes[index - 1]

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        true_ranges.append(true_range)

    period_decimal = Decimal(period)

    initial_atr = (
        sum(
            true_ranges[:period],
            start=_DECIMAL_ZERO,
        )
        / period_decimal
    )

    atr_values: list[Decimal] = [
        initial_atr,
    ]
    previous_atr = initial_atr

    for true_range in true_ranges[period:]:
        current_atr = (
            (previous_atr * (period_decimal - Decimal("1"))) + true_range
        ) / period_decimal

        atr_values.append(current_atr)
        previous_atr = current_atr

    return tuple(atr_values)
