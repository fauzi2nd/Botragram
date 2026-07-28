import threading

class OrderBook:

    def __init__(self):
        self.lock = threading.Lock()
        self.best_bid = None
        self.best_ask = None

    def update(self, data):
        with self.lock:
            self.best_bid = data["b"][0]
            self.best_ask = data["a"][0]

    def get_best_prices(self):
        with self.lock:
            return self.best_bid, self.best_ask
