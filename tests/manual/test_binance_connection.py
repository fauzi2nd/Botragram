"""
Botragram

Description:
    Test binance connection.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
import asyncio

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.exchange_type import ExchangeType
from botragram.enums.interval import Interval
from botragram.exchanges.factory import ExchangeFactory


# =============================================================================
# Test Binance Connection
# =============================================================================
async def main() -> None:
    exchange_client, stream_client = ExchangeFactory.create(
        exchange_type=ExchangeType.BINANCE,
        rest_base_url="https://api.binance.com",
        websocket_base_url="wss://stream.binance.com:9443",
    )

    try:
        await exchange_client.connect()
        await stream_client.connect()

        print(f"REST ping: {await exchange_client.ping()}")
        print(f"Stream session connected: {stream_client.is_connected}")

        ticker_stream = stream_client.stream_ticker(
            symbol="BTCUSDT",
        )

        async with asyncio.timeout(15):
            ticker = await anext(ticker_stream)

        print("\n")
        print("Ticker received:")
        print(f"  symbol: {ticker.symbol}")
        print(f"  bid: {ticker.bid_price}")
        print(f"  ask: {ticker.ask_price}")
        print(f"  last: {ticker.last_price}")
        print(f"  timestamp: {ticker.timestamp}")

    finally:
        await stream_client.close()
        await exchange_client.close()


async def test_candle_stream() -> None:
    _, stream_client = ExchangeFactory.create(
        exchange_type=ExchangeType.BINANCE,
        rest_base_url="https://api.binance.com",
        websocket_base_url="wss://stream.binance.com:9443",
    )

    try:
        await stream_client.connect()

        candle_stream = stream_client.stream_candles(
            symbol="BTCUSDT",
            interval=Interval.M1,
        )

        async with asyncio.timeout(15):
            candle = await anext(candle_stream)

        print("\n")
        print("Candle received:")
        print(f"  symbol: {candle.symbol}")
        print(f"  open time: {candle.open_time}")
        print(f"  close time: {candle.close_time}")
        print(f"  open: {candle.open_price}")
        print(f"  high: {candle.high_price}")
        print(f"  low: {candle.low_price}")
        print(f"  close: {candle.close_price}")
        print(f"  volume: {candle.volume}")

    finally:
        await stream_client.close()


async def read_ticker_updates() -> None:
    _, stream_client = ExchangeFactory.create(
        exchange_type=ExchangeType.BINANCE,
        rest_base_url="https://api.binance.com",
        websocket_base_url="wss://stream.binance.com:9443",
    )

    try:
        await stream_client.connect()

        ticker_stream = stream_client.stream_ticker(
            symbol="BTCUSDT",
        )

        async with asyncio.timeout(20):
            update_count = 0
            print("\n")
            async for ticker in ticker_stream:
                print(
                    ticker.timestamp,
                    ticker.symbol,
                    ticker.last_price,
                )

                update_count += 1

                if update_count >= 5:
                    break

    finally:
        await stream_client.close()


async def test_unsubscribe() -> None:
    _, stream_client = ExchangeFactory.create(
        exchange_type=ExchangeType.BINANCE,
        rest_base_url="https://api.binance.com",
        websocket_base_url="wss://stream.binance.com:9443",
    )

    async def consume() -> None:
        async for ticker in stream_client.stream_ticker(
            symbol="BTCUSDT",
        ):
            print(ticker.last_price)

        print("Consumer stopped")

    try:
        await stream_client.connect()

        consumer = asyncio.create_task(consume())

        await asyncio.sleep(5)

        await stream_client.unsubscribe(
            symbol="BTCUSDT",
        )

        async with asyncio.timeout(5):
            await consumer

        print("Subscription permanently closed")

    finally:
        await stream_client.close()


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(test_candle_stream())
    asyncio.run(read_ticker_updates())
    asyncio.run(test_unsubscribe())
