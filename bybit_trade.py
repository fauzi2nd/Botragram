from pybit.unified_trading import WebSocket
import threading
import time
from trade_aggregator import TradeAggregator

aggregator = TradeAggregator("BTCUSDT")

def handle_trade(message):

    trades = message["data"]

    for trade in trades:

        aggregator.add_trade(trade["S"], float(trade["v"]))

def summary():

    while True:
        time.sleep(1)

        data = aggregator.get_summary()

        print("\n===== 1 SECOND SUMMARY =====")
        print(f"Buy Volume : {data['buy_volume']:.3f}")
        print(f"Sell Volume: {data['sell_volume']:.3f}")
        print(f"Buy Count  : {data['buy_count']}")
        print(f"Sell Count : {data['sell_count']}")

        aggregator.reset()

ws = WebSocket(
    testnet=False,
    channel_type="linear",
)

ws.trade_stream(
    symbol="BTCUSDT",
    callback=handle_trade,
)

print("Trade Stream Connected")

threading.Thread(
    target=summary,
    daemon=True
).start()

while True:
    time.sleep(1)
