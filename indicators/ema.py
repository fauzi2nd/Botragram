from indicators.base import Indicator


class EMA(Indicator):

    def __init__(self, period):
        self.period = period
        self.value = None

    def update(self, candles):
        if len(candles) < self.period:
            return None

        closes = [c.close for c in candles]

        k = 2 / (self.period + 1)

        ema = sum(closes[:self.period]) / self.period

        for close in closes[self.period:]:
            ema = close * k + ema * (1 - k)

        self.value = ema
        return ema
