"""
Botragram

Description:
    Supertrend technical indicator.

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
from botragram.exchanges.base.mapper import Candle
from botragram.indicators.atr import calculate_atr


# =============================================================================
# Data Model
# =============================================================================
@dataclass(slots=True)
class SupertrendResult:
    """Supertrend indicator output value and trend direction."""

    value: Decimal
    is_uptrend: bool


# =============================================================================
# Function
# =============================================================================
def calculate_supertrend(
    candles: list[Candle],
    period: int = 10,
    multiplier: Decimal = Decimal("3.0"),
) -> list[SupertrendResult]:
    """Calculate Supertrend indicator from candle series.

    Args:
        candles: List of Candle instances.
        period: ATR period length.
        multiplier: ATR multiplier coefficient.

    Returns:
        List of SupertrendResult instances.
    """
    atr_values = calculate_atr(candles, period)
    if not atr_values:
        return []

    offset = len(candles) - len(atr_values)
    trimmed_candles = candles[offset:]

    results: list[SupertrendResult] = []
    upper_band = Decimal("0")
    lower_band = Decimal("0")
    is_uptrend = True

    for candle, atr in zip(trimmed_candles, atr_values):
        hl2 = (candle.high_price + candle.low_price) / Decimal("2")
        basic_upper = hl2 + (multiplier * atr)
        basic_lower = hl2 - (multiplier * atr)

        if not results:
            upper_band = basic_upper
            lower_band = basic_lower
            supertrend_val = lower_band
        else:
            prev_close = trimmed_candles[results.index(results[-1])].close_price
            upper_band = (
                basic_upper
                if basic_upper < upper_band or prev_close > upper_band
                else upper_band
            )
            lower_band = (
                basic_lower
                if basic_lower > lower_band or prev_close < lower_band
                else lower_band
            )

            if is_uptrend:
                if candle.close_price < lower_band:
                    is_uptrend = False
                    supertrend_val = upper_band
                else:
                    supertrend_val = lower_band
            else:
                if candle.close_price > upper_band:
                    is_uptrend = True
                    supertrend_val = lower_band
                else:
                    supertrend_val = upper_band

        results.append(
            SupertrendResult(value=supertrend_val, is_uptrend=is_uptrend)
        )

    return results
