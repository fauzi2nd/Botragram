import threading
import time

from exchanges.bybit.ws_client import BybitWebSocketClient
from exchanges.bybit.trade_stream import TradeStream
from core.trade_aggregator import TradeAggregator


aggregator = TradeAggregator("BTCUSDT")
trade_stream = TradeStream(aggregator)


def summary():

    while True:
        time.sleep(1)

        data = aggregator.consume_summary()

        print("\n===== 1 SECOND SUMMARY =====")
        print(f"Buy Volume : {data['buy_volume']:.3f}")
        print(f"Sell Volume: {data['sell_volume']:.3f}")
        print(f"Buy Count  : {data['buy_count']}")
        print(f"Sell Count : {data['sell_count']}")


client = BybitWebSocketClient()

client.connect()

client.subscribe_trade(
    "BTCUSDT",
    trade_stream.handle_message,
)

threading.Thread(
    target=summary,
    daemon=True,
).start()


while True:
    time.sleep(1)
