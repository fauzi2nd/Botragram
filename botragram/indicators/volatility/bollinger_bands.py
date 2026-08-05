"""
Botragram

Description:
    Bollinger Bands indicator.

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
from decimal import Decimal, localcontext

# =============================================================================
# Local Imports
# =============================================================================
from botragram.indicators.trend.sma import calculate_sma

__all__ = [
    "BollingerBandsResult",
    "calculate_bollinger_bands",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# Result Models
# =============================================================================
@dataclass(
    slots=True,
    frozen=True,
)
class BollingerBandsResult:
    """Calculated Bollinger Bands values."""

    upper: tuple[Decimal, ...]
    middle: tuple[Decimal, ...]
    lower: tuple[Decimal, ...]


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_bollinger_bands(
    values: Sequence[Decimal],
    *,
    period: int = 20,
    standard_deviation: Decimal = Decimal("2"),
) -> BollingerBandsResult:
    """Calculate Bollinger Bands.

    Args:
        values: Ordered prices from oldest to newest.
        period: Moving-average lookback period.
        standard_deviation: Standard-deviation multiplier.

    Returns:
        Upper, middle, and lower Bollinger Bands.

    Raises:
        ValueError: If configuration or input values are invalid.
    """
    if period <= 0:
        raise ValueError("Bollinger Bands period must be greater than zero")

    if standard_deviation < _DECIMAL_ZERO:
        raise ValueError("Bollinger Bands standard deviation must not be negative")

    if len(values) < period:
        raise ValueError(
            "Bollinger Bands requires at least as many values as its period"
        )

    middle_band = calculate_sma(
        values,
        period=period,
    )

    upper_band: list[Decimal] = []
    lower_band: list[Decimal] = []
    period_decimal = Decimal(period)

    for index, middle_value in enumerate(middle_band):
        window_start = index
        window_end = index + period
        window = values[window_start:window_end]

        variance = (
            sum(
                ((value - middle_value) ** 2 for value in window),
                start=_DECIMAL_ZERO,
            )
            / period_decimal
        )

        with localcontext() as context:
            context.prec += 8
            deviation = variance.sqrt()

        distance = deviation * standard_deviation

        upper_band.append(middle_value + distance)
        lower_band.append(middle_value - distance)

    return BollingerBandsResult(
        upper=tuple(upper_band),
        middle=middle_band,
        lower=tuple(lower_band),
    )
