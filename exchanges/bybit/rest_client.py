from pybit.unified_trading import HTTP


class BybitRESTClient:

    def __init__(self):
        self.client = HTTP(
            testnet=False,
        )

    def get_kline(self, symbol, interval, limit=200):
        response = self.client.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=limit,
        )

        return response["result"]["list"]
