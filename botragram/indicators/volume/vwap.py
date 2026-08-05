"""
Botragram

Description:
    Volume Weighted Average Price indicator.

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
    "calculate_vwap",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_THREE = Decimal("3")


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_vwap(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    closes: Sequence[Decimal],
    volumes: Sequence[Decimal],
) -> tuple[Decimal, ...]:
    """Calculate cumulative Volume Weighted Average Price values.

    Args:
        highs: Ordered high prices from oldest to newest.
        lows: Ordered low prices from oldest to newest.
        closes: Ordered close prices from oldest to newest.
        volumes: Ordered trading volumes from oldest to newest.

    Returns:
        Cumulative VWAP values aligned with the input sequences.

    Raises:
        ValueError: If sequences are empty, have different lengths,
            contain negative volume values, or cumulative volume is zero.
    """
    sequence_length = len(closes)

    if not (len(highs) == len(lows) == sequence_length == len(volumes)):
        raise ValueError("VWAP price and volume sequences must have equal lengths")

    if sequence_length == 0:
        raise ValueError("VWAP input sequences must not be empty")

    if any(volume < _DECIMAL_ZERO for volume in volumes):
        raise ValueError("VWAP volume values must not be negative")

    cumulative_price_volume = _DECIMAL_ZERO
    cumulative_volume = _DECIMAL_ZERO
    vwap_values: list[Decimal] = []

    for high, low, close, volume in zip(
        highs,
        lows,
        closes,
        volumes,
        strict=True,
    ):
        typical_price = (high + low + close) / _DECIMAL_THREE

        cumulative_price_volume += typical_price * volume
        cumulative_volume += volume

        if cumulative_volume == _DECIMAL_ZERO:
            raise ValueError("VWAP cumulative volume must be greater than zero")

        vwap_values.append(cumulative_price_volume / cumulative_volume)

    return tuple(vwap_values)
