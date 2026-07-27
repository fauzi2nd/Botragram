from pybit.unified_trading import WebSocket


class BybitWebSocketClient:

    def __init__(self):
        self.ws = None

    def connect(self):
        self.ws = WebSocket(
            testnet=False,
            channel_type="linear",
        )

        print("Bybit WebSocket Connected")

    def subscribe_trade(self, symbol, callback):
        self.ws.trade_stream(
            symbol=symbol,
            callback=callback,
        )
