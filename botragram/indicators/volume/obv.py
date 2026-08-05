"""
Botragram

Description:
    On-Balance Volume indicator.

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
    "calculate_obv",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_obv(
    closes: Sequence[Decimal],
    volumes: Sequence[Decimal],
) -> tuple[Decimal, ...]:
    """Calculate On-Balance Volume values.

    Args:
        closes: Ordered closing prices from oldest to newest.
        volumes: Ordered trading volumes from oldest to newest.

    Returns:
        OBV values aligned with the supplied input sequences.

    Raises:
        ValueError: If input sequences are empty, have different lengths,
            or contain negative volume values.
    """
    if len(closes) != len(volumes):
        raise ValueError("OBV close and volume sequences must have equal lengths")

    if not closes:
        raise ValueError("OBV input sequences must not be empty")

    if any(volume < _DECIMAL_ZERO for volume in volumes):
        raise ValueError("OBV volume values must not be negative")

    current_obv = _DECIMAL_ZERO
    obv_values: list[Decimal] = [
        current_obv,
    ]

    for index in range(1, len(closes)):
        current_close = closes[index]
        previous_close = closes[index - 1]
        current_volume = volumes[index]

        if current_close > previous_close:
            current_obv += current_volume
        elif current_close < previous_close:
            current_obv -= current_volume

        obv_values.append(current_obv)

    return tuple(obv_values)
