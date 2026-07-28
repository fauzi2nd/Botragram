from strategies.base import Strategy
from strategies.signal import Signal


class EmaRsiStrategy(Strategy):

    def analyze(self, market):

        ema20 = market.indicators.ema20
        ema50 = market.indicators.ema50
        rsi = market.indicators.rsi14

        if None in (ema20, ema50, rsi):
            return Signal.HOLD

        if ema20 > ema50 and rsi > 55:
            return Signal.BUY

        if ema20 < ema50 and rsi < 45:
            return Signal.SELL

        return Signal.HOLD
