from pybit.unified_trading import WebSocket
from core.exchange import Exchange


class BybitWebSocketClient(Exchange):
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

    def subscribe_ticker(self, symbol, callback):
        self.ws.ticker_stream(
            symbol=symbol,
            callback=callback,
        )
    def subscribe_orderbook(self, symbol, callback):
        self.ws.orderbook_stream(
            depth=50,
            symbol=symbol,
            callback=callback,
        )

    def subscribe_kline(self, symbol, interval, callback):
        self.ws.kline_stream(
            symbol=symbol,
            interval=interval,
            callback=callback,
        )
