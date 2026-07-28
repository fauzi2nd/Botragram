class Candle:

    def __init__(
        self,
        start: int,
        end: int,
        interval: str,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        turnover: float,
        confirm: bool,
    ):
        self.start = start
        self.end = end
        self.interval = interval
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.turnover = turnover
        self.confirm = confirm

    def __repr__(self):
        return (
            f"Candle("
            f"O={self.open}, "
            f"H={self.high}, "
            f"L={self.low}, "
            f"C={self.close})"
        )
