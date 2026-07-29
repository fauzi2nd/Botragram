"""
Botragram

Description:
    Average True Range (ATR) technical indicator.

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
from botragram.exchanges.base.mapper import Candle


# =============================================================================
# Function
# =============================================================================
def calculate_atr(candles: list[Candle], period: int = 14) -> list[Decimal]:
    """Calculate Average True Range (ATR) from candlestick series.

    Args:
        candles: List of Candle objects.
        period: ATR period length.

    Returns:
        List of calculated Decimal ATR values.
    """
    if len(candles) <= period or period <= 0:
        return []

    true_ranges: list[Decimal] = []
    for i in range(1, len(candles)):
        current = candles[i]
        prev_close = candles[i - 1].close_price

        tr1 = current.high_price - current.low_price
        tr2 = abs(current.high_price - prev_close)
        tr3 = abs(current.low_price - prev_close)

        tr = max(tr1, tr2, tr3)
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return []

    initial_atr = sum(true_ranges[:period], Decimal("0")) / Decimal(period)
    atr_values: list[Decimal] = [initial_atr]

    period_dec = Decimal(period)
    for tr in true_ranges[period:]:
        prev_atr = atr_values[-1]
        current_atr = (prev_atr * (period_dec - Decimal("1")) + tr) / period_dec
        atr_values.append(current_atr)

    return atr_values
