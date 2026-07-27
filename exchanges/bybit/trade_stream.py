class TradeStream:

    def __init__(self, aggregator):
        self.aggregator = aggregator

    def handle_message(self, message):

        trades = message["data"]

        for trade in trades:
            self.aggregator.add_trade(
                trade["S"],
                float(trade["v"])
            )
