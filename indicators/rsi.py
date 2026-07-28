from indicators.base import Indicator


class RSI(Indicator):

    def __init__(self, period=14):
        self.period = period
        self.value = None

    def update(self, candles):
        if len(candles) < self.period + 1:
            return None

        closes = [c.close for c in candles]

        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]

            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains[-self.period:]) / self.period
        avg_loss = sum(losses[-self.period:]) / self.period

        if avg_loss == 0:
            self.value = 100
            return 100

        rs = avg_gain / avg_loss
        self.value = 100 - (100 / (1 + rs))

        return self.value
