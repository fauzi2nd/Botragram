"""
Botragram

Description:
    Parabolic Stop and Reverse indicator.

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
    "PSARResult",
    "calculate_psar",
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
class PSARResult:
    """Calculated Parabolic SAR values."""

    values: tuple[Decimal, ...]
    is_uptrend: tuple[bool, ...]


# =============================================================================
# Indicator Functions
# =============================================================================


def _update_psar_for_uptrend(
    psar: Decimal,
    acceleration_factor: Decimal,
    index: int,
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    extreme_point: Decimal,
    acceleration_step: Decimal,
    acceleration_maximum: Decimal,
) -> tuple[Decimal, bool, Decimal, Decimal]:
    psar = min(
        psar,
        lows[index - 1],
        lows[index - 2] if index >= 2 else lows[index - 1],
    )

    if lows[index] < psar:
        return extreme_point, False, lows[index], acceleration_step

    if highs[index] > extreme_point:
        extreme_point = highs[index]
        acceleration_factor = min(
            acceleration_factor + acceleration_step,
            acceleration_maximum,
        )

    return psar, True, extreme_point, acceleration_factor


def _update_psar_for_downtrend(
    psar: Decimal,
    acceleration_factor: Decimal,
    index: int,
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    extreme_point: Decimal,
    acceleration_step: Decimal,
    acceleration_maximum: Decimal,
) -> tuple[Decimal, bool, Decimal, Decimal]:
    psar = max(
        psar,
        highs[index - 1],
        highs[index - 2] if index >= 2 else highs[index - 1],
    )

    if highs[index] > psar:
        return extreme_point, True, highs[index], acceleration_step

    if lows[index] < extreme_point:
        extreme_point = lows[index]
        acceleration_factor = min(
            acceleration_factor + acceleration_step,
            acceleration_maximum,
        )

    return psar, False, extreme_point, acceleration_factor


def calculate_psar(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    *,
    acceleration_step: Decimal = Decimal("0.02"),
    acceleration_maximum: Decimal = Decimal("0.20"),
) -> PSARResult:
    """Calculate Parabolic Stop and Reverse values.

    Args:
        highs: Ordered high prices from oldest to newest.
        lows: Ordered low prices from oldest to newest.
        acceleration_step: Acceleration factor increment.
        acceleration_maximum: Maximum acceleration factor.

    Returns:
        PSAR values and trend direction aligned with the input sequences.

    Raises:
        ValueError: If input sequences or acceleration settings are invalid.
    """
    if len(highs) != len(lows):
        raise ValueError("PSAR high and low sequences must have equal lengths")

    if len(highs) < 2:
        raise ValueError("PSAR requires at least two price values")

    if acceleration_step <= _DECIMAL_ZERO:
        raise ValueError("PSAR acceleration step must be greater than zero")

    if acceleration_maximum <= _DECIMAL_ZERO:
        raise ValueError("PSAR acceleration maximum must be greater than zero")

    if acceleration_step > acceleration_maximum:
        raise ValueError("PSAR acceleration step must not exceed its maximum")

    uptrend = highs[1] >= highs[0]

    psar = lows[0] if uptrend else highs[0]
    extreme_point = highs[0] if uptrend else lows[0]
    acceleration_factor = acceleration_step

    psar_values: list[Decimal] = [psar]
    trend_values: list[bool] = [uptrend]

    for index in range(1, len(highs)):
        psar = psar + acceleration_factor * (extreme_point - psar)

        if uptrend:
            (
                psar,
                uptrend,
                extreme_point,
                acceleration_factor,
            ) = _update_psar_for_uptrend(
                psar,
                acceleration_factor,
                index,
                highs,
                lows,
                extreme_point,
                acceleration_step,
                acceleration_maximum,
            )
        else:
            (
                psar,
                uptrend,
                extreme_point,
                acceleration_factor,
            ) = _update_psar_for_downtrend(
                psar,
                acceleration_factor,
                index,
                highs,
                lows,
                extreme_point,
                acceleration_step,
                acceleration_maximum,
            )

        psar_values.append(psar)
        trend_values.append(uptrend)

    return PSARResult(
        values=tuple(psar_values),
        is_uptrend=tuple(trend_values),
    )
