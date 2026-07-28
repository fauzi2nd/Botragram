import threading
import time

from core.market_state import MarketState
from exchanges.bybit.ws_client import BybitWebSocketClient
from exchanges.bybit.trade_stream import TradeStream
from core.trade_aggregator import TradeAggregator
from exchanges.bybit.orderbook_stream import OrderBookStream
from core.orderbook import OrderBook
from core.ticker import Ticker
from exchanges.bybit.ticker_stream import TickerStream
from core.kline import Kline
from exchanges.bybit.kline_stream import KlineStream

market = MarketState()
orderbook = OrderBook()
orderbook_stream = OrderBookStream(orderbook)

aggregator = TradeAggregator("BTCUSDT")
trade_stream = TradeStream(aggregator)

market.trade = aggregator
market.orderbook = orderbook
ticker = Ticker()
market.ticker = ticker

ticker_stream = TickerStream(ticker)

kline = Kline()
market.kline = kline

kline_stream = KlineStream(kline)

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

client.subscribe_ticker(
    "BTCUSDT",
    ticker_stream.handle_message,
)

client.subscribe_kline(
    symbol="BTCUSDT",
    interval=1,
    callback=kline_stream.handle_message,
)

#threading.Thread(
#    target=summary,
#    daemon=True,
#).start()


while True:
    time.sleep(1)

#    bid, ask = market.orderbook.get_best_prices()

 #   if bid and ask:
  #      print(
   #         f"Bid: {bid[0]} ({bid[1]}) | "
    #        f"Ask: {ask[0]} ({ask[1]})"
     #   )

#    ticker = market.ticker.snapshot()

 #   print(
#        f"Last: {ticker['last_price']} | "
#        f"Mark: {ticker['mark_price']} | "
#        f"Funding: {ticker['funding_rate']}"
#    )

    candle = market.kline.snapshot()

    if candle:
        print(
            f"O:{candle.open} "
            f"H:{candle.high} "
            f"L:{candle.low} "
            f"C:{candle.close} "
            f"Confirmed:{candle.confirm}"
        )

    candles = market.kline.get_candles()

    print(f"Closed Candles: {len(candles)}")
