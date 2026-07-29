"""
Botragram

Description:
    EMA Crossover trading strategy implementation.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.signal_type import SignalType
from botragram.exchanges.base.mapper import Candle
from botragram.indicators.ema import calculate_ema
from botragram.strategies.base_strategy import BaseStrategy


# =============================================================================
# Strategy Class
# =============================================================================
class EMACrossStrategy(BaseStrategy):
    """Trading strategy based on fast/slow EMA crossovers."""

    def __init__(self, fast_period: int = 9, slow_period: int = 21) -> None:
        """Initialize EMA Cross Strategy.

        Args:
            fast_period: Fast EMA period length.
            slow_period: Slow EMA period length.
        """
        super().__init__(name="EMA_CROSS")
        self._fast_period = fast_period
        self._slow_period = slow_period

    def generate_signal(self, candles: list[Candle]) -> SignalType:
        """Evaluate EMA crossover on candles.

        Args:
            candles: List of Candle objects.

        Returns:
            BUY_ENTRY, SELL_ENTRY, or NEUTRAL signal.
        """
        if len(candles) < self._slow_period + 1:
            return SignalType.NEUTRAL

        closes = [c.close_price for c in candles]
        fast_ema = calculate_ema(closes, self._fast_period)
        slow_ema = calculate_ema(closes, self._slow_period)

        if len(fast_ema) < 2 or len(slow_ema) < 2:
            return SignalType.NEUTRAL

        # Compare current and previous EMA values
        prev_fast, curr_fast = fast_ema[-2], fast_ema[-1]
        prev_slow, curr_slow = slow_ema[-2], slow_ema[-1]

        # Bullish Crossover (Fast crosses above Slow)
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            return SignalType.BUY_ENTRY

        # Bearish Crossover (Fast crosses below Slow)
        if prev_fast >= prev_slow and curr_fast < curr_slow:
            return SignalType.SELL_ENTRY

        return SignalType.NEUTRAL
