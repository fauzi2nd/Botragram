"""
Botragram

Description:
    Simple Moving Average (SMA) technical indicator.

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
# Function
# =============================================================================
def calculate_sma(prices: list[Decimal], period: int) -> list[Decimal]:
    """Calculate Simple Moving Average for a series of Decimal prices.

    Args:
        prices: List of Decimal close prices.
        period: Moving average period length.

    Returns:
        List of calculated Decimal SMA values.
    """
    if len(prices) < period or period <= 0:
        return []

    sma_values: list[Decimal] = []
    for i in range(len(prices) - period + 1):
        window = prices[i : i + period]
        avg = sum(window, Decimal("0")) / Decimal(period)
        sma_values.append(avg)

    return sma_values
