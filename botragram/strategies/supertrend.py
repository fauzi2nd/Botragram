"""
Botragram

Description:
    Supertrend trend-following strategy implementation.

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
from botragram.enums.signal_type import SignalType
from botragram.exchanges.base.mapper import Candle
from botragram.indicators.supertrend import calculate_supertrend
from botragram.strategies.base_strategy import BaseStrategy


# =============================================================================
# Strategy Class
# =============================================================================
class SupertrendStrategy(BaseStrategy):
    """Trading strategy following Supertrend trend flips."""

    def __init__(
        self,
        period: int = 10,
        multiplier: Decimal = Decimal("3.0"),
    ) -> None:
        """Initialize Supertrend strategy.

        Args:
            period: ATR period length.
            multiplier: ATR multiplier coefficient.
        """
        super().__init__(name="SUPERTREND")
        self._period = period
        self._multiplier = multiplier

    def generate_signal(self, candles: list[Candle]) -> SignalType:
        """Evaluate Supertrend direction flips.

        Args:
            candles: List of Candle objects.

        Returns:
            BUY_ENTRY, SELL_ENTRY, or NEUTRAL signal.
        """
        if len(candles) < self._period + 2:
            return SignalType.NEUTRAL

        results = calculate_supertrend(
            candles, period=self._period, multiplier=self._multiplier
        )

        if len(results) < 2:
            return SignalType.NEUTRAL

        prev_trend = results[-2].is_uptrend
        curr_trend = results[-1].is_uptrend

        # Trend flip from Bearish to Bullish
        if not prev_trend and curr_trend:
            return SignalType.BUY_ENTRY

        # Trend flip from Bullish to Bearish
        if prev_trend and not curr_trend:
            return SignalType.SELL_ENTRY

        return SignalType.NEUTRAL
