"""
Botragram

Description:
    Exponential Moving Average indicator.

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
    "calculate_ema",
]


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_ema(
    values: Sequence[Decimal],
    *,
    period: int,
) -> tuple[Decimal, ...]:
    """Calculate Exponential Moving Average values.

    Args:
        values: Ordered numeric values from oldest to newest.
        period: EMA lookback period.

    Returns:
        EMA values beginning from the first complete period.

    Raises:
        ValueError: If the period or input values are invalid.
    """
    if period <= 0:
        raise ValueError("EMA period must be greater than zero")

    if len(values) < period:
        raise ValueError("EMA requires at least as many values as its period")

    period_decimal = Decimal(period)
    multiplier = Decimal("2") / (period_decimal + Decimal("1"))

    initial_average = (
        sum(
            values[:period],
            start=Decimal("0"),
        )
        / period_decimal
    )

    ema_values: list[Decimal] = [
        initial_average,
    ]
    previous_ema = initial_average

    for value in values[period:]:
        current_ema = (value - previous_ema) * multiplier + previous_ema
        ema_values.append(current_ema)
        previous_ema = current_ema

    return tuple(ema_values)
