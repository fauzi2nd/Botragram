import threading


class Ticker:

    def __init__(self):
        self.lock = threading.Lock()

        self.last_price = None
        self.mark_price = None
        self.index_price = None
        self.funding_rate = None
        self.open_interest = None

    def update(self, data):
        with self.lock:
            self.last_price = float(data["lastPrice"])
            self.mark_price = float(data["markPrice"])
            self.index_price = float(data["indexPrice"])
            self.funding_rate = float(data["fundingRate"])
            self.open_interest = float(data["openInterest"])

    def snapshot(self):
        with self.lock:
            return {
                "last_price": self.last_price,
                "mark_price": self.mark_price,
                "index_price": self.index_price,
                "funding_rate": self.funding_rate,
                "open_interest": self.open_interest,
            }
