"""
Botragram

Description:
    Ichimoku Cloud indicator.

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
    "IchimokuResult",
    "calculate_ichimoku",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_TWO = Decimal("2")


# =============================================================================
# Result Models
# =============================================================================
@dataclass(
    slots=True,
    frozen=True,
)
class IchimokuResult:
    """Calculated Ichimoku Cloud values."""

    conversion_line: tuple[Decimal, ...]
    base_line: tuple[Decimal, ...]
    leading_span_a: tuple[Decimal, ...]
    leading_span_b: tuple[Decimal, ...]
    lagging_span: tuple[Decimal, ...]


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_ichimoku(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    closes: Sequence[Decimal],
    *,
    conversion_period: int = 9,
    base_period: int = 26,
    leading_span_period: int = 52,
) -> IchimokuResult:
    """Calculate Ichimoku Cloud components.

    Args:
        highs: Ordered high prices from oldest to newest.
        lows: Ordered low prices from oldest to newest.
        closes: Ordered close prices from oldest to newest.
        conversion_period: Tenkan-sen lookback period.
        base_period: Kijun-sen lookback and displacement period.
        leading_span_period: Senkou Span B lookback period.

    Returns:
        Ichimoku component values aligned from the first complete
        leading-span period.

    Raises:
        ValueError: If periods or input sequences are invalid.
    """
    if conversion_period <= 0:
        raise ValueError("Ichimoku conversion period must be greater than zero")

    if base_period <= 0:
        raise ValueError("Ichimoku base period must be greater than zero")

    if leading_span_period <= 0:
        raise ValueError("Ichimoku leading span period must be greater than zero")

    if not (conversion_period <= base_period <= leading_span_period):
        raise ValueError(
            "Ichimoku periods must satisfy "
            "conversion_period <= base_period <= leading_span_period"
        )

    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("Ichimoku price sequences must have equal lengths")

    if len(closes) < leading_span_period:
        raise ValueError(
            "Ichimoku requires at least as many values as its leading span period"
        )

    conversion_values = _calculate_midpoints(
        highs,
        lows,
        period=conversion_period,
    )
    base_values = _calculate_midpoints(
        highs,
        lows,
        period=base_period,
    )
    leading_span_b_values = _calculate_midpoints(
        highs,
        lows,
        period=leading_span_period,
    )

    conversion_offset = leading_span_period - conversion_period
    base_offset = leading_span_period - base_period

    aligned_conversion = conversion_values[conversion_offset:]
    aligned_base = base_values[base_offset:]

    leading_span_a: tuple[Decimal, ...] = tuple(
        (conversion_value + base_value) / _DECIMAL_TWO
        for conversion_value, base_value in zip(
            aligned_conversion,
            aligned_base,
            strict=True,
        )
    )

    lagging_span = tuple(
        closes[leading_span_period - base_period : len(closes) - base_period + 1]
    )

    return IchimokuResult(
        conversion_line=aligned_conversion,
        base_line=aligned_base,
        leading_span_a=leading_span_a,
        leading_span_b=leading_span_b_values,
        lagging_span=lagging_span,
    )


# =============================================================================
# Helper Functions
# =============================================================================
def _calculate_midpoints(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    *,
    period: int,
) -> tuple[Decimal, ...]:
    """Calculate rolling high-low midpoint values."""
    midpoints: list[Decimal] = []

    for end_index in range(
        period,
        len(highs) + 1,
    ):
        start_index = end_index - period
        high_window = highs[start_index:end_index]
        low_window = lows[start_index:end_index]

        highest_high = max(high_window)
        lowest_low = min(low_window)

        midpoints.append((highest_high + lowest_low) / _DECIMAL_TWO)

    return tuple(midpoints)
