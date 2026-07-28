from models.candle import Candle


class HistoryLoader:

    def __init__(self, rest_client):
        self.rest = rest_client

    def load(self, market, symbol, interval="1", limit=200):
        data = self.rest.get_kline(
            symbol=symbol,
            interval=interval,
            limit=limit,
        )

        # Bybit mengembalikan candle dari yang terbaru ke yang terlama
        data.reverse()

        for row in data:

            candle = Candle(
                start=int(row[0]),
                end=int(row[0]),
                interval=interval,
                open_price=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                turnover=float(row[6]),
                confirm=True,
            )

            market.kline.candles.append(candle)

        print(f"Loaded {len(market.kline.candles)} candles")
