class TradeAggregator:

    def __init__(self, symbol):
        self.symbol = symbol

        self.buy_volume = 0.0
        self.sell_volume = 0.0

        self.buy_count = 0
        self.sell_count = 0

    def add_trade(self, side, volume):

        if side == "Buy":
           self.buy_volume += volume
           self.buy_count += 1

        else:
           self.sell_volume += volume
           self.sell_count += 1

    def reset(self):

        self.buy_volume = 0.0
        self.sell_volume = 0.0

        self.buy_count = 0
        self.sell_count = 0

    def get_summary(self):
        return {
          "buy_volume": self.buy_volume,
          "sell_volume": self.sell_volume,
          "buy_count": self.buy_count,
          "sell_count": self.sell_count,
        }
