"""
Botragram

Description:
    Stochastic RSI (StochRSI) momentum indicator.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.indicators.momentum.rsi import calculate_rsi
from botragram.indicators.trend.sma import calculate_sma

__all__ = [
    "StochRSIResult",
    "calculate_stoch_rsi",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_FIFTY = Decimal("50")
_DECIMAL_ONE_HUNDRED = Decimal("100")


# =============================================================================
# Data Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class StochRSIResult:
    """Aligned Stochastic RSI %K and %D indicator series."""

    k: tuple[Decimal, ...]
    d: tuple[Decimal, ...]


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_stoch_rsi(
    values: Sequence[Decimal],
    *,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_period: int = 3,
    d_period: int = 3,
) -> StochRSIResult:
    """Calculate Stochastic RSI indicator.

    Computes the Stochastic oscillator of Relative Strength Index values,
    smoothed by Simple Moving Averages for %K and %D lines.

    Args:
        values: Ordered closing prices from oldest to newest.
        rsi_period: Lookback period for base RSI calculation.
        stoch_period: Lookback period for Stochastic min/max extraction.
        k_period: Smoothing period for %K line.
        d_period: Smoothing period for %D line.

    Returns:
        Aligned StochRSIResult containing %K and %D tuples with equal lengths.

    Raises:
        ValueError: If any period is <= 0 or input values are insufficient.
    """
    if rsi_period <= 0:
        raise ValueError("RSI period must be greater than zero")

    if stoch_period <= 0:
        raise ValueError("Stoch period must be greater than zero")

    if k_period <= 0:
        raise ValueError("K period must be greater than zero")

    if d_period <= 0:
        raise ValueError("D period must be greater than zero")

    min_required = rsi_period + stoch_period + k_period + d_period - 2
    if len(values) < min_required:
        raise ValueError(
            f"Stochastic RSI requires at least {min_required} values, "
            f"but received {len(values)}"
        )

    rsi_series = calculate_rsi(values, period=rsi_period)

    if len(rsi_series) < stoch_period:
        raise ValueError("Insufficient RSI points to compute Stochastic range")

    raw_stoch: list[Decimal] = []
    for index in range(stoch_period - 1, len(rsi_series)):
        window = rsi_series[index - stoch_period + 1 : index + 1]
        min_rsi = min(window)
        max_rsi = max(window)
        diff = max_rsi - min_rsi

        if diff == _DECIMAL_ZERO:
            raw_stoch.append(_DECIMAL_FIFTY)
        else:
            stoch = ((window[-1] - min_rsi) / diff) * _DECIMAL_ONE_HUNDRED
            bounded = min(max(stoch, _DECIMAL_ZERO), _DECIMAL_ONE_HUNDRED)
            raw_stoch.append(bounded)

    k_raw = calculate_sma(raw_stoch, period=k_period)
    d_series = calculate_sma(k_raw, period=d_period)

    alignment_offset = d_period - 1
    k_aligned = k_raw[alignment_offset:]

    return StochRSIResult(
        k=k_aligned,
        d=d_series,
    )
