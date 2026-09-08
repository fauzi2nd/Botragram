"""
Botragram

Description:
    Multi-timeframe trend evaluation and directional filter.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

# =============================================================================
# Local Imports
# =============================================================================
from botragram.indicators.trend.ema import calculate_ema
from botragram.models import Candle

# =============================================================================
# Public Exports
# =============================================================================
__all__ = [
    "MtfTrendResult",
    "TrendDirection",
    "evaluate_mtf_trend",
]


class TrendDirection(StrEnum):
    """Directional market trend status on a higher timeframe."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(slots=True, kw_only=True, frozen=True)
class MtfTrendResult:
    """Result of higher timeframe trend evaluation."""

    direction: TrendDirection
    current_close: Decimal
    ema_value: Decimal | None
    is_aligned_with_buy: bool
    is_aligned_with_sell: bool


def evaluate_mtf_trend(
    candles: Sequence[Candle],
    *,
    ema_period: int = 50,
) -> MtfTrendResult:
    """Evaluate market trend on a higher timeframe using closed candle prices.

    Args:
        candles: Sequence of closed candles from higher timeframe.
        ema_period: Lookback period for trend EMA (default 50).

    Returns:
        MtfTrendResult detailing direction and directional alignment.
    """
    if not candles or len(candles) < ema_period:
        last_close = candles[-1].close_price if candles else Decimal("0")
        return MtfTrendResult(
            direction=TrendDirection.NEUTRAL,
            current_close=last_close,
            ema_value=None,
            is_aligned_with_buy=True,
            is_aligned_with_sell=True,
        )

    close_prices = [c.close_price for c in candles]
    ema_series = calculate_ema(close_prices, period=ema_period)
    latest_ema = ema_series[-1]
    latest_close = close_prices[-1]

    if latest_close > latest_ema:
        direction = TrendDirection.BULLISH
        aligned_buy = True
        aligned_sell = False
    elif latest_close < latest_ema:
        direction = TrendDirection.BEARISH
        aligned_buy = False
        aligned_sell = True
    else:
        direction = TrendDirection.NEUTRAL
        aligned_buy = True
        aligned_sell = True

    return MtfTrendResult(
        direction=direction,
        current_close=latest_close,
        ema_value=latest_ema,
        is_aligned_with_buy=aligned_buy,
        is_aligned_with_sell=aligned_sell,
    )
