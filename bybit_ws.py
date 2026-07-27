from pybit.unified_trading import WebSocket
import time

print("1. Program started")

def handle_message(message):
    data = message["data"]

    print(
        f"Price: {data['lastPrice']} | "
        f"Bid: {data['bid1Price']} | "
        f"Ask: {data['ask1Price']}"
    )

print("2. Creating websocket...")

ws = WebSocket(
    testnet=False,
    channel_type="linear",
)

print("3. WebSocket created")

ws.ticker_stream(
    symbol="BTCUSDT",
    callback=handle_message,
)

print("4. Subscribed")

while True:
    time.sleep(1)
