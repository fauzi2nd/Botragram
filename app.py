import threading
import time

from core.market_state import MarketState
from exchanges.bybit.ws_client import BybitWebSocketClient
from exchanges.bybit.trade_stream import TradeStream
from core.trade_aggregator import TradeAggregator
from exchanges.bybit.orderbook_stream import OrderBookStream
from core.orderbook import OrderBook

market = MarketState()
orderbook = OrderBook()
orderbook_stream = OrderBookStream(orderbook)

aggregator = TradeAggregator("BTCUSDT")
trade_stream = TradeStream(aggregator)

market.trade = aggregator
market.orderbook = orderbook

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

client.subscribe_orderbook(                         "BTCUSDT",
    orderbook_stream.handle_message,            )

#threading.Thread(
#    target=summary,
#    daemon=True,
#).start()


while True:
    time.sleep(1)

    bid, ask = market.orderbook.get_best_prices()

    if bid and ask:
        print(
            f"Bid: {bid[0]} ({bid[1]}) | "
            f"Ask: {ask[0]} ({ask[1]})"
        )
