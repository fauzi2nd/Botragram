"""
Botragram

Description:
    Moving Average Convergence Divergence indicator.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

from collections.abc import Sequence

# =============================================================================
# Standard Library
# =============================================================================
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.indicators.trend.ema import calculate_ema

__all__ = [
    "MACDResult",
    "calculate_macd",
]


# =============================================================================
# Result Models
# =============================================================================
@dataclass(
    slots=True,
    frozen=True,
)
class MACDResult:
    """Calculated MACD values."""

    macd: tuple[Decimal, ...]
    signal: tuple[Decimal, ...]
    histogram: tuple[Decimal, ...]


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_macd(
    values: Sequence[Decimal],
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MACDResult:
    """Calculate Moving Average Convergence Divergence values.

    Args:
        values: Ordered closing prices from oldest to newest.
        fast_period: Fast EMA period.
        slow_period: Slow EMA period.
        signal_period: Signal EMA period.

    Returns:
        MACD line, signal line, and histogram values.

    Raises:
        ValueError: If periods or input values are invalid.
    """
    if fast_period <= 0:
        raise ValueError("MACD fast period must be greater than zero")

    if slow_period <= 0:
        raise ValueError("MACD slow period must be greater than zero")

    if signal_period <= 0:
        raise ValueError("MACD signal period must be greater than zero")

    if fast_period >= slow_period:
        raise ValueError("MACD fast period must be less than slow period")

    minimum_values = slow_period + signal_period - 1

    if len(values) < minimum_values:
        raise ValueError(f"MACD requires at least {minimum_values} values")

    fast_ema = calculate_ema(
        values,
        period=fast_period,
    )
    slow_ema = calculate_ema(
        values,
        period=slow_period,
    )

    offset = slow_period - fast_period
    aligned_fast_ema = fast_ema[offset:]

    macd_line: tuple[Decimal, ...] = tuple(
        fast_value - slow_value
        for fast_value, slow_value in zip(
            aligned_fast_ema,
            slow_ema,
            strict=True,
        )
    )

    signal_line = calculate_ema(
        macd_line,
        period=signal_period,
    )

    aligned_macd_line = macd_line[signal_period - 1 :]

    histogram: tuple[Decimal, ...] = tuple(
        macd_value - signal_value
        for macd_value, signal_value in zip(
            aligned_macd_line,
            signal_line,
            strict=True,
        )
    )

    return MACDResult(
        macd=aligned_macd_line,
        signal=signal_line,
        histogram=histogram,
    )
