"""
Botragram

Description:
    EMA Crossover strategy with RSI overbought/oversold filter.

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
from botragram.indicators.ema import calculate_ema
from botragram.indicators.rsi import calculate_rsi
from botragram.strategies.base_strategy import BaseStrategy


# =============================================================================
# Strategy Class
# =============================================================================
class EMARSIStrategy(BaseStrategy):
    """Trading strategy combining EMA trend filter and RSI boundaries."""

    def __init__(
        self,
        ema_period: int = 50,
        rsi_period: int = 14,
        rsi_oversold: Decimal = Decimal("30.0"),
        rsi_overbought: Decimal = Decimal("70.0"),
    ) -> None:
        """Initialize EMA + RSI strategy.

        Args:
            ema_period: Trend filter EMA period.
            rsi_period: RSI indicator period.
            rsi_oversold: Oversold RSI threshold.
            rsi_overbought: Overbought RSI threshold.
        """
        super().__init__(name="EMA_RSI")
        self._ema_period = ema_period
        self._rsi_period = rsi_period
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought

    def generate_signal(self, candles: list[Candle]) -> SignalType:
        """Evaluate EMA and RSI on candle series.

        Args:
            candles: List of Candle objects.

        Returns:
            BUY_ENTRY, SELL_ENTRY, or NEUTRAL signal.
        """
        min_length = max(self._ema_period, self._rsi_period) + 1
        if len(candles) < min_length:
            return SignalType.NEUTRAL

        closes = [c.close_price for c in candles]
        ema_values = calculate_ema(closes, self._ema_period)
        rsi_values = calculate_rsi(closes, self._rsi_period)

        if not ema_values or not rsi_values:
            return SignalType.NEUTRAL

        curr_close = closes[-1]
        curr_ema = ema_values[-1]
        curr_rsi = rsi_values[-1]

        # Buy condition: Price above EMA and RSI recovering from oversold
        if curr_close > curr_ema and curr_rsi <= self._rsi_oversold:
            return SignalType.BUY_ENTRY

        # Sell condition: Price below EMA and RSI in overbought zone
        if curr_close < curr_ema and curr_rsi >= self._rsi_overbought:
            return SignalType.SELL_ENTRY

        return SignalType.NEUTRAL
