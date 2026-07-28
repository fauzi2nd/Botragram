class OrderBookStream:

    def __init__(self, orderbook):
        self.orderbook = orderbook

    def handle_message(self, message):
        self.orderbook.update(message["data"])
