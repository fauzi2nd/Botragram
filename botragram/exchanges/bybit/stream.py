"""
Botragram

Description:
    Bybit V5 WebSocket streaming client.

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
import json
import logging
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal
from typing import Final, cast

# =============================================================================
# Third-Party Imports
# =============================================================================
import aiohttp

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.interval import Interval
from botragram.exchanges.base import BaseStreamClient
from botragram.exchanges.base.mapper import ExchangePayload
from botragram.exchanges.bybit.client import BYBIT_INTERVAL_MAP
from botragram.exchanges.bybit.mapper import BybitExchangeMapper
from botragram.models import Candle, Ticker

__all__ = [
    "BybitStreamClient",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS: Final[float] = 20.0
_PING_MESSAGE: Final[str] = json.dumps({"op": "ping"})
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")


# =============================================================================
# Stream Client Implementation
# =============================================================================
class BybitStreamClient(BaseStreamClient):
    """Bybit V5 WebSocket streaming client."""

    __slots__ = (
        "_connected",
        "_heartbeat_task",
        "_mapper",
        "_queues",
        "_read_task",
        "_session",
        "_subscriptions",
        "_ticker_cache",
        "_websocket",
        "_websocket_url",
    )

    def __init__(
        self,
        *,
        websocket_url: str,
        mapper: BybitExchangeMapper,
    ) -> None:
        """Initialize the Bybit streaming client."""
        self._websocket_url: str = websocket_url.rstrip("/")
        self._mapper: BybitExchangeMapper = mapper
        self._session: aiohttp.ClientSession | None = None
        self._websocket: aiohttp.ClientWebSocketResponse | None = None
        self._connected: bool = False
        self._subscriptions: set[str] = set()
        self._queues: dict[str, set[asyncio.Queue[object]]] = {}
        self._ticker_cache: dict[str, dict[str, object]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        """Return whether the WebSocket connection is active."""
        return (
            self._connected
            and self._websocket is not None
            and not self._websocket.closed
        )

    async def connect(self) -> None:
        """Open the WebSocket connection and start background handlers."""
        if self.is_connected:
            return

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

        try:
            self._websocket = await self._session.ws_connect(self._websocket_url)
            self._connected = True
            self._read_task = asyncio.create_task(self._read_messages())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            _LOGGER.info("Connected to Bybit WebSocket at %s", self._websocket_url)

            # Resubscribe active topics if reconnecting
            if self._subscriptions and self._websocket:
                sub_msg = json.dumps(
                    {"op": "subscribe", "args": list(self._subscriptions)}
                )
                await self._websocket.send_str(sub_msg)
        except Exception as error:
            self._connected = False
            _LOGGER.error(
                "Failed to connect to Bybit WebSocket %s: %s",
                self._websocket_url,
                error,
            )
            raise

    async def close(self) -> None:
        """Close WebSocket connection and clean up resources."""
        self._connected = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        if self._read_task is not None:
            self._read_task.cancel()
            self._read_task = None

        if self._websocket is not None and not self._websocket.closed:
            await self._websocket.close()
            self._websocket = None

        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

        self._ticker_cache.clear()
        _LOGGER.info("Bybit WebSocket connection closed")

    async def _heartbeat_loop(self) -> None:
        """Send ping every 20 seconds to keep connection alive."""
        try:
            while self._connected:
                await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
                if self._websocket is not None and not self._websocket.closed:
                    await self._websocket.send_str(_PING_MESSAGE)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            _LOGGER.warning("Bybit WebSocket heartbeat error: %s", error)

    async def _read_messages(self) -> None:
        """Read and dispatch incoming Bybit WebSocket frames."""
        try:
            while (
                self._connected
                and self._websocket is not None
                and not self._websocket.closed
            ):
                msg = await self._websocket.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as error:
            _LOGGER.warning("Bybit WebSocket read error: %s", error)
        finally:
            self._connected = False

    def handle_message(self, raw_data: str) -> None:
        """Parse Bybit V5 message frame and dispatch to queues."""
        self._handle_message(raw_data)

    def get_cached_ticker(self, symbol: str) -> Mapping[str, object] | None:
        """Return cached raw ticker payload for a symbol, if any."""
        return self._ticker_cache.get(symbol.strip().upper())

    def _handle_message(self, raw_data: str) -> None:
        """Parse Bybit V5 message frame and dispatch to queues."""
        try:
            raw_payload = json.loads(raw_data)
        except Exception:
            return

        if not isinstance(raw_payload, dict):
            return

        payload = cast(ExchangePayload, raw_payload)

        # Ignore pong replies
        if payload.get("op") == "pong" or payload.get("ret_msg") == "pong":
            return

        topic = payload.get("topic")
        if not isinstance(topic, str):
            return

        # Handle ticker topic
        if topic.startswith("tickers."):
            data = payload.get("data")
            msg_type = payload.get("type")
            if isinstance(data, dict):
                data_dict = cast(dict[str, object], data)
                parts = topic.split(".")
                symbol = (
                    parts[1]
                    if len(parts) >= 2
                    else str(data_dict.get("symbol", "")).strip().upper()
                )

                cached = self._ticker_cache.get(symbol)
                if msg_type == "snapshot" or cached is None:
                    merged = dict(data_dict)
                else:
                    merged = dict(cached)
                    merged.update(data_dict)
                self._ticker_cache[symbol] = merged

                queues = self._queues.get(topic)
                if queues:
                    ticker = self._mapper.map_stream_ticker(
                        cast(ExchangePayload, merged)
                    )
                    if ticker.last_price > _DECIMAL_ZERO:
                        for q in tuple(queues):
                            q.put_nowait(ticker)

        elif topic.startswith("kline."):
            queues = self._queues.get(topic)
            if not queues:
                return
            data = payload.get("data")
            if isinstance(data, list) and data:
                kline_list = cast(list[object], data)
                kline_item = kline_list[0]
                if isinstance(kline_item, dict):
                    parts = topic.split(".")
                    symbol = parts[2] if len(parts) >= 3 else ""
                    candle = self._mapper.map_stream_candle(
                        cast(ExchangePayload, kline_item),
                        symbol=symbol,
                        interval=Interval.M5,
                    )
                    for q in tuple(queues):
                        q.put_nowait(candle)

    async def _subscribe(self, topic: str) -> None:
        """Subscribe to a Bybit topic."""
        self._subscriptions.add(topic)
        if (
            self.is_connected
            and self._websocket is not None
            and not self._websocket.closed
        ):
            sub_msg = json.dumps({"op": "subscribe", "args": [topic]})
            await self._websocket.send_str(sub_msg)

    async def unsubscribe(self, *, symbol: str) -> None:
        """Unsubscribe all topics associated with a symbol."""
        normalized_symbol = symbol.strip().upper()
        self._ticker_cache.pop(normalized_symbol, None)
        topics_to_remove = [t for t in self._subscriptions if normalized_symbol in t]
        for topic in topics_to_remove:
            self._subscriptions.discard(topic)
            self._queues.pop(topic, None)
            if (
                self.is_connected
                and self._websocket is not None
                and not self._websocket.closed
            ):
                unsub_msg = json.dumps({"op": "unsubscribe", "args": [topic]})
                await self._websocket.send_str(unsub_msg)

    async def stream_ticker(
        self,
        *,
        symbol: str,
    ) -> AsyncIterator[Ticker]:
        """Stream real-time ticker updates for a symbol."""
        topic = f"tickers.{symbol.strip().upper()}"
        queue: asyncio.Queue[object] = asyncio.Queue()

        if topic not in self._queues:
            self._queues[topic] = set()
        self._queues[topic].add(queue)

        await self._subscribe(topic)

        try:
            while self._connected:
                item = await queue.get()
                if isinstance(item, Ticker):
                    yield item
        finally:
            if topic in self._queues:
                self._queues[topic].discard(queue)
                if not self._queues[topic]:
                    self._queues.pop(topic, None)

    async def stream_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
    ) -> AsyncIterator[Candle]:
        """Stream real-time candlestick updates for a symbol."""
        interval_code = BYBIT_INTERVAL_MAP.get(interval, "15")
        topic = f"kline.{interval_code}.{symbol.strip().upper()}"
        queue: asyncio.Queue[object] = asyncio.Queue()

        if topic not in self._queues:
            self._queues[topic] = set()
        self._queues[topic].add(queue)

        await self._subscribe(topic)

        try:
            while self._connected:
                item = await queue.get()
                if isinstance(item, Candle):
                    # Ensure candle carries caller interval
                    yield Candle(
                        symbol=item.symbol,
                        interval=interval,
                        open_time=item.open_time,
                        close_time=item.close_time,
                        open_price=item.open_price,
                        high_price=item.high_price,
                        low_price=item.low_price,
                        close_price=item.close_price,
                        volume=item.volume,
                    )
        finally:
            if topic in self._queues:
                self._queues[topic].discard(queue)
                if not self._queues[topic]:
                    self._queues.pop(topic, None)
