from indicators.ema import EMA
from indicators.rsi import RSI


class IndicatorManager:

    def __init__(self):
        # Calculator
        self._ema20 = EMA(20)
        self._ema50 = EMA(50)
        self._ema200 = EMA(200)
        self._rsi14 = RSI(14)

        # Latest values
        self.ema20 = None
        self.ema50 = None
        self.ema200 = None
        self.rsi14 = None

    def update(self, candles):
        self.ema20 = self._ema20.update(candles)
        self.ema50 = self._ema50.update(candles)
        self.ema200 = self._ema200.update(candles)
        self.rsi14 = self._rsi14.update(candles)
