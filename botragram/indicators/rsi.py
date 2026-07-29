"""
Botragram

Description:
    Relative Strength Index (RSI) technical indicator.

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
def calculate_rsi(prices: list[Decimal], period: int = 14) -> list[Decimal]:
    """Calculate Relative Strength Index (RSI) for a series of Decimal prices.

    Args:
        prices: List of Decimal close prices.
        period: RSI period length (default 14).

    Returns:
        List of calculated Decimal RSI values (0 to 100).
    """
    if len(prices) <= period or period <= 0:
        return []

    gains: list[Decimal] = []
    losses: list[Decimal] = []

    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > Decimal("0"):
            gains.append(change)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(abs(change))

    if len(gains) < period:
        return []

    avg_gain = sum(gains[:period], Decimal("0")) / Decimal(period)
    avg_loss = sum(losses[:period], Decimal("0")) / Decimal(period)

    rsi_values: list[Decimal] = []
    if avg_loss == Decimal("0"):
        rsi_values.append(Decimal("100"))
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(Decimal("100") - (Decimal("100") / (Decimal("1") + rs)))

    period_dec = Decimal(period)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period_dec - Decimal("1")) + gains[i]) / period_dec
        avg_loss = (avg_loss * (period_dec - Decimal("1")) + losses[i]) / period_dec

        if avg_loss == Decimal("0"):
            rsi_values.append(Decimal("100"))
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(
                Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
            )

    return rsi_values
