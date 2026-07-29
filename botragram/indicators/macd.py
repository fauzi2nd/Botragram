"""
Botragram

Description:
    Moving Average Convergence Divergence (MACD) technical indicator.

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
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.indicators.ema import calculate_ema


# =============================================================================
# Data Model
# =============================================================================
@dataclass(slots=True)
class MACDResult:
    """MACD indicator output components."""

    macd_line: Decimal
    signal_line: Decimal
    histogram: Decimal


# =============================================================================
# Function
# =============================================================================
def calculate_macd(
    prices: list[Decimal],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> list[MACDResult]:
    """Calculate MACD indicator series.

    Args:
        prices: List of Decimal close prices.
        fast_period: Fast EMA period length.
        slow_period: Slow EMA period length.
        signal_period: Signal line EMA period length.

    Returns:
        List of MACDResult instances.
    """
    if len(prices) < slow_period:
        return []

    fast_ema = calculate_ema(prices, fast_period)
    slow_ema = calculate_ema(prices, slow_period)

    offset = slow_period - fast_period
    fast_ema_trimmed = fast_ema[offset:]

    macd_lines: list[Decimal] = [
        f - s for f, s in zip(fast_ema_trimmed, slow_ema)
    ]

    signal_lines = calculate_ema(macd_lines, signal_period)

    results: list[MACDResult] = []
    macd_trimmed = macd_lines[signal_period - 1 :]

    for macd_val, signal_val in zip(macd_trimmed, signal_lines):
        results.append(
            MACDResult(
                macd_line=macd_val,
                signal_line=signal_val,
                histogram=macd_val - signal_val,
            )
        )

    return results
