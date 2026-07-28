from indicators.ema import EMA
from indicators.rsi import RSI


class IndicatorManager:

    def __init__(self):
        self.ema20 = EMA(20)
        self.ema50 = EMA(50)
        self.ema200 = EMA(200)

        self.rsi14 = RSI(14)

    def update(self, candles):
        return {
            "ema20": self.ema20.update(candles),
            "ema50": self.ema50.update(candles),
            "ema200": self.ema200.update(candles),
            "rsi14": self.rsi14.update(candles),
        }
