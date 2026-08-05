"""
Botragram

Description:
    Simple Moving Average indicator.

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
    "calculate_sma",
]


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_sma(
    values: Sequence[Decimal],
    *,
    period: int,
) -> tuple[Decimal, ...]:
    """Calculate Simple Moving Average values.

    Args:
        values: Ordered numeric values from oldest to newest.
        period: SMA lookback period.

    Returns:
        SMA values beginning from the first complete period.

    Raises:
        ValueError: If the period or input values are invalid.
    """
    if period <= 0:
        raise ValueError("SMA period must be greater than zero")

    if len(values) < period:
        raise ValueError("SMA requires at least as many values as its period")

    period_decimal = Decimal(period)
    window_sum = sum(
        values[:period],
        start=Decimal("0"),
    )

    sma_values: list[Decimal] = [
        window_sum / period_decimal,
    ]

    for index in range(period, len(values)):
        window_sum += values[index]
        window_sum -= values[index - period]

        sma_values.append(window_sum / period_decimal)

    return tuple(sma_values)
