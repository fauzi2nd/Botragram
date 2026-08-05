"""
Botragram

Description:
    Relative Strength Index indicator.

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
    "calculate_rsi",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE_HUNDRED = Decimal("100")


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_rsi(
    values: Sequence[Decimal],
    *,
    period: int,
) -> tuple[Decimal, ...]:
    """Calculate Relative Strength Index (RSI).

    Uses Wilder's smoothing method.

    Args:
        values: Ordered closing prices from oldest to newest.
        period: RSI lookback period.

    Returns:
        RSI values beginning after the first complete period.

    Raises:
        ValueError: If the period or input values are invalid.
    """
    if period <= 0:
        raise ValueError("RSI period must be greater than zero")

    if len(values) <= period:
        raise ValueError("RSI requires more values than its period")

    gains: list[Decimal] = []
    losses: list[Decimal] = []

    for previous, current in zip(
        values,
        values[1:],
        strict=False,
    ):
        change = current - previous

        if change >= _DECIMAL_ZERO:
            gains.append(change)
            losses.append(_DECIMAL_ZERO)
        else:
            gains.append(_DECIMAL_ZERO)
            losses.append(-change)

    period_decimal = Decimal(period)

    average_gain = (
        sum(
            gains[:period],
            start=_DECIMAL_ZERO,
        )
        / period_decimal
    )

    average_loss = (
        sum(
            losses[:period],
            start=_DECIMAL_ZERO,
        )
        / period_decimal
    )

    rsi_values: list[Decimal] = [
        _calculate_rsi(
            average_gain,
            average_loss,
        )
    ]

    for gain, loss in zip(
        gains[period:],
        losses[period:],
        strict=False,
    ):
        average_gain = (
            (average_gain * (period_decimal - Decimal("1"))) + gain
        ) / period_decimal

        average_loss = (
            (average_loss * (period_decimal - Decimal("1"))) + loss
        ) / period_decimal

        rsi_values.append(
            _calculate_rsi(
                average_gain,
                average_loss,
            )
        )

    return tuple(rsi_values)


# =============================================================================
# Helper Functions
# =============================================================================
def _calculate_rsi(
    average_gain: Decimal,
    average_loss: Decimal,
) -> Decimal:
    """Return one RSI value."""
    if average_loss == _DECIMAL_ZERO:
        return _DECIMAL_ONE_HUNDRED

    relative_strength = average_gain / average_loss

    return _DECIMAL_ONE_HUNDRED - (
        _DECIMAL_ONE_HUNDRED / (Decimal("1") + relative_strength)
    )
