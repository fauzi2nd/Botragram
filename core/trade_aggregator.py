import threading

class TradeAggregator:

    def __init__(self, symbol):
        self.symbol = symbol

        self.buy_volume = 0.0
        self.sell_volume = 0.0

        self.buy_count = 0
        self.sell_count = 0
        self.lock = threading.Lock()

    def add_trade(self, side, volume):
        with self.lock:
            if side == "Buy":
              self.buy_volume += volume
              self.buy_count += 1

            else:
              self.sell_volume += volume
              self.sell_count += 1

    def consume_summary(self):
        with self.lock:

            data = {
                "buy_volume": self.buy_volume,
                "sell_volume": self.sell_volume,
                "buy_count": self.buy_count,
                "sell_count": self.sell_count,
            }

            self.buy_volume = 0.0
            self.sell_volume = 0.0
            self.buy_count = 0
            self.sell_count = 0

            return data
