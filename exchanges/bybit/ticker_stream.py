class TickerStream:

    def __init__(self, ticker):
        self.ticker = ticker

    def handle_message(self, message):
        self.ticker.update(message["data"])
