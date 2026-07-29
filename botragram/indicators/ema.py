"""
Botragram

Description:
    Exponential Moving Average (EMA) technical indicator.

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
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.indicators.sma import calculate_sma


# =============================================================================
# Function
# =============================================================================
def calculate_ema(prices: list[Decimal], period: int) -> list[Decimal]:
    """Calculate Exponential Moving Average for a series of Decimal prices.

    Args:
        prices: List of Decimal close prices.
        period: Moving average period length.

    Returns:
        List of calculated Decimal EMA values.
    """
    if len(prices) < period or period <= 0:
        return []

    # Initial EMA value starts as SMA of first period
    initial_sma = calculate_sma(prices[:period], period)
    if not initial_sma:
        return []

    multiplier = Decimal("2") / Decimal(period + 1)
    ema_values: list[Decimal] = [initial_sma[0]]

    for price in prices[period:]:
        prev_ema = ema_values[-1]
        current_ema = (price - prev_ema) * multiplier + prev_ema
        ema_values.append(current_ema)

    return ema_values
