import threading
from models.candle import Candle
from collections import deque

class Kline:

    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.candles = deque(maxlen=500)

    def update(self, data):
        candle = Candle(
            start=int(data["start"]),
            end=int(data["end"]),
            interval=data["interval"],
            open_price=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=float(data["volume"]),
            turnover=float(data["turnover"]),
            confirm=data["confirm"]
        )

        with self.lock:
            self.current = candle

            if candle.confirm:
                self.candles.append(candle)

    def get_candles(self):
        with self.lock:
            return list(self.candles)
    
    def snapshot(self):
        with self.lock:
            return self.current

    def last(self, n):
        with self.lock:
            return list(self.candles)[-n:]
