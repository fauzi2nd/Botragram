"""
Botragram

Description:
    Binance Spot WebSocket streaming client.

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
from collections.abc import AsyncIterator, Callable, Mapping
from random import SystemRandom
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
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.models import Candle, Ticker
from botragram.utils.retry import CappedExponentialBackoff

__all__ = [
    "BinanceStreamClient",
]


# =============================================================================
# Queue Marker
# =============================================================================
class _StreamClosed:
    """Mark the end of an internal subscription queue."""

    __slots__ = ()


_STREAM_CLOSED: Final[_StreamClosed] = _StreamClosed()


# =============================================================================
# Type Aliases
# =============================================================================
type StreamQueueItem = ExchangePayload | _StreamClosed
type StreamQueue = asyncio.Queue[StreamQueueItem]
type StreamTask = asyncio.Task[None]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_TICKER_STREAM_SUFFIX: Final[str] = "@ticker"
_KLINE_STREAM_PREFIX: Final[str] = "@kline_"

_TICKER_EVENT_TYPE: Final[str] = "24hrTicker"
_KLINE_EVENT_TYPE: Final[str] = "kline"

_DEFAULT_HEARTBEAT_SECONDS: Final[float] = 30.0
_DEFAULT_RECONNECT_DELAY_SECONDS: Final[float] = 1.0
_DEFAULT_MAXIMUM_RECONNECT_DELAY_SECONDS: Final[float] = 60.0
_DEFAULT_RECONNECT_JITTER_RATIO: Final[float] = 0.2
_DEFAULT_RECEIVE_TIMEOUT_SECONDS: Final[float] = 60.0
_DEFAULT_QUEUE_MAX_SIZE: Final[int] = 1_000


def _random_fraction() -> float:
    """Return isolated jitter for one public-stream transport."""
    return SystemRandom().random()


# =============================================================================
# Binance Stream Client
# =============================================================================
class BinanceStreamClient(BaseStreamClient):
    """Stream Binance Spot market data through WebSocket connections.

    Each public iterator owns one producer task and one bounded queue. The
    producer handles connection and reconnection while the iterator only
    consumes validated payloads. Unsubscribing marks matching streams as
    cancelled before their sockets and producer tasks are stopped, preventing
    an automatic reconnect race.
    """

    __slots__ = (
        "_active_sockets",
        "_base_url",
        "_cancelled_streams",
        "_heartbeat_seconds",
        "_mapper",
        "_queue_max_size",
        "_receive_timeout_seconds",
        "_reconnect_backoff",
        "_reconnect_delay_seconds",
        "_session",
        "_state_lock",
        "_stream_tasks",
    )

    def __init__(
        self,
        *,
        base_url: str,
        mapper: BinanceExchangeMapper,
        heartbeat_seconds: float = _DEFAULT_HEARTBEAT_SECONDS,
        receive_timeout_seconds: float = _DEFAULT_RECEIVE_TIMEOUT_SECONDS,
        reconnect_delay_seconds: float = _DEFAULT_RECONNECT_DELAY_SECONDS,
        maximum_reconnect_delay_seconds: float = (
            _DEFAULT_MAXIMUM_RECONNECT_DELAY_SECONDS
        ),
        reconnect_jitter_ratio: float = _DEFAULT_RECONNECT_JITTER_RATIO,
        random_source: Callable[[], float] = _random_fraction,
        queue_max_size: int = _DEFAULT_QUEUE_MAX_SIZE,
    ) -> None:
        """Initialize the Binance streaming client."""
        normalized_base_url = base_url.rstrip("/")

        if not normalized_base_url:
            raise ValueError("WebSocket base URL must not be empty")

        if heartbeat_seconds <= 0:
            raise ValueError("WebSocket heartbeat must be greater than zero")

        if receive_timeout_seconds <= 0:
            raise ValueError("WebSocket receive timeout must be greater than zero")

        if reconnect_delay_seconds < 0:
            raise ValueError("WebSocket reconnect delay must not be negative")

        if maximum_reconnect_delay_seconds <= 0:
            raise ValueError("Maximum WebSocket reconnect delay must be positive")

        if (
            reconnect_delay_seconds > 0
            and maximum_reconnect_delay_seconds < reconnect_delay_seconds
        ):
            raise ValueError("Maximum reconnect delay must cover the initial delay")

        if queue_max_size <= 0:
            raise ValueError("WebSocket queue size must be greater than zero")

        self._base_url = normalized_base_url
        self._mapper = mapper
        self._heartbeat_seconds = heartbeat_seconds
        self._receive_timeout_seconds = receive_timeout_seconds
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._reconnect_backoff = (
            CappedExponentialBackoff(
                initial_delay_seconds=reconnect_delay_seconds,
                maximum_delay_seconds=maximum_reconnect_delay_seconds,
                jitter_ratio=reconnect_jitter_ratio,
                random_source=random_source,
            )
            if reconnect_delay_seconds > 0
            else None
        )
        self._queue_max_size = queue_max_size

        self._session: aiohttp.ClientSession | None = None
        self._active_sockets: dict[
            str,
            set[aiohttp.ClientWebSocketResponse],
        ] = {}
        self._stream_tasks: dict[
            str,
            set[StreamTask],
        ] = {}
        self._cancelled_streams: set[str] = set()
        self._state_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        """Return whether the streaming transport is available."""
        session = self._session
        return session is not None and not session.closed

    async def connect(self) -> None:
        """Create the HTTP session used by WebSocket subscriptions."""
        session = self._session

        if session is None or session.closed:
            self._session = aiohttp.ClientSession()

    def stream_ticker(
        self,
        *,
        symbol: str,
    ) -> AsyncIterator[Ticker]:
        """Stream 24-hour ticker updates for a trading symbol."""
        normalized_symbol = self._normalize_symbol(symbol)
        stream_name = f"{normalized_symbol.lower()}{_TICKER_STREAM_SUFFIX}"

        return self._stream_ticker(
            stream_name=stream_name,
        )

    def stream_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
    ) -> AsyncIterator[Candle]:
        """Stream candlestick updates for a trading symbol."""
        normalized_symbol = self._normalize_symbol(symbol)
        stream_interval = self._normalize_interval(interval)
        stream_name = (
            f"{normalized_symbol.lower()}{_KLINE_STREAM_PREFIX}{stream_interval}"
        )

        return self._stream_candles(
            stream_name=stream_name,
        )

    async def unsubscribe(
        self,
        *,
        symbol: str,
    ) -> None:
        """Permanently stop active subscriptions for a trading symbol.

        A later call to ``stream_ticker`` or ``stream_candles`` for the same
        symbol creates a new subscription and re-enables its specific stream.
        """
        normalized_symbol = self._normalize_symbol(symbol).lower()
        prefix = f"{normalized_symbol}@"

        async with self._state_lock:
            matching_streams = {
                stream_name
                for stream_name in (
                    self._active_sockets.keys() | self._stream_tasks.keys()
                )
                if stream_name.startswith(prefix)
            }

            self._cancelled_streams.update(matching_streams)

            sockets = tuple(
                socket
                for stream_name in matching_streams
                for socket in self._active_sockets.get(
                    stream_name,
                    set(),
                )
            )
            tasks = tuple(
                task
                for stream_name in matching_streams
                for task in self._stream_tasks.get(
                    stream_name,
                    set(),
                )
            )

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        if sockets:
            await asyncio.gather(
                *(socket.close() for socket in sockets if not socket.closed),
                return_exceptions=True,
            )

    async def close(self) -> None:
        """Stop all subscriptions and release network resources."""
        async with self._state_lock:
            stream_names = self._active_sockets.keys() | self._stream_tasks.keys()
            self._cancelled_streams.update(stream_names)

            sockets = tuple(
                socket
                for stream_sockets in self._active_sockets.values()
                for socket in stream_sockets
            )
            tasks = tuple(
                task
                for stream_tasks in self._stream_tasks.values()
                for task in stream_tasks
            )

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        if sockets:
            await asyncio.gather(
                *(socket.close() for socket in sockets if not socket.closed),
                return_exceptions=True,
            )

        async with self._state_lock:
            self._active_sockets.clear()
            self._stream_tasks.clear()

        session = self._session

        if session is not None and not session.closed:
            await session.close()

        self._session = None

    async def _stream_ticker(
        self,
        *,
        stream_name: str,
    ) -> AsyncIterator[Ticker]:
        """Yield mapped ticker updates from one queued subscription."""
        async for payload in self._consume_payloads(
            stream_name=stream_name,
            expected_event_type=_TICKER_EVENT_TYPE,
        ):
            yield self._mapper.map_stream_ticker(payload)

    async def _stream_candles(
        self,
        *,
        stream_name: str,
    ) -> AsyncIterator[Candle]:
        """Yield mapped candle updates from one queued subscription."""
        async for payload in self._consume_payloads(
            stream_name=stream_name,
            expected_event_type=_KLINE_EVENT_TYPE,
        ):
            yield self._mapper.map_stream_candle(payload)

    async def _consume_payloads(
        self,
        *,
        stream_name: str,
        expected_event_type: str,
    ) -> AsyncIterator[ExchangePayload]:
        """Consume payloads produced by a background WebSocket task."""
        self._require_session()

        queue: StreamQueue = asyncio.Queue(
            maxsize=self._queue_max_size,
        )

        async with self._state_lock:
            self._cancelled_streams.discard(stream_name)

        producer = asyncio.create_task(
            self._produce_payloads(
                stream_name=stream_name,
                expected_event_type=expected_event_type,
                queue=queue,
            ),
            name=f"binance-stream:{stream_name}",
        )
        await self._register_task(
            stream_name=stream_name,
            task=producer,
        )

        try:
            while True:
                item = await queue.get()

                if isinstance(item, _StreamClosed):
                    break

                yield item
        finally:
            producer.cancel()

            await asyncio.gather(
                producer,
                return_exceptions=True,
            )

            await self._unregister_task(
                stream_name=stream_name,
                task=producer,
            )

    async def _produce_payloads(
        self,
        *,
        stream_name: str,
        expected_event_type: str,
        queue: StreamQueue,
    ) -> None:
        """Receive payloads and place them in a bounded queue."""
        reconnect_attempt = 0
        try:
            while self.is_connected and not await self._is_cancelled(stream_name):
                connected = await self._connect_and_consume_stream(
                    stream_name=stream_name,
                    expected_event_type=expected_event_type,
                    queue=queue,
                )

                if self.is_connected and not await self._is_cancelled(stream_name):
                    reconnect_attempt = 1 if connected else reconnect_attempt + 1
                    await asyncio.sleep(
                        self._get_reconnect_delay(attempt=reconnect_attempt)
                    )
        finally:
            self._put_stream_closed(queue)

    async def _connect_and_consume_stream(
        self,
        *,
        stream_name: str,
        expected_event_type: str,
        queue: StreamQueue,
    ) -> bool:
        socket: aiohttp.ClientWebSocketResponse | None = None
        connected = False

        try:
            session = self._require_session()
            socket = await session.ws_connect(
                self._build_stream_url(stream_name),
                heartbeat=self._heartbeat_seconds,
                receive_timeout=self._receive_timeout_seconds,
                autoclose=True,
                autoping=True,
            )
            connected = True
            await self._register_socket(
                stream_name=stream_name,
                socket=socket,
            )

            await self._consume_socket_messages(
                socket=socket,
                stream_name=stream_name,
                expected_event_type=expected_event_type,
                queue=queue,
            )
        except asyncio.CancelledError:
            raise
        except (
            aiohttp.ClientError,
            TimeoutError,
            RuntimeError,
            ValueError,
        ) as error:
            if not self.is_connected or await self._is_cancelled(stream_name):
                return connected

            _LOGGER.warning(
                "Binance WebSocket stream interrupted; reconnecting",
                extra={
                    "error": str(error),
                    "stream_name": stream_name,
                },
            )
        finally:
            if socket is not None:
                await self._unregister_socket(
                    stream_name=stream_name,
                    socket=socket,
                )

                if not socket.closed:
                    await socket.close()
        return connected

    def _get_reconnect_delay(self, *, attempt: int) -> float:
        """Return one capped reconnect delay while retaining zero-delay tests."""
        backoff = self._reconnect_backoff
        return 0.0 if backoff is None else backoff.get_delay(attempt=attempt)

    async def _consume_socket_messages(
        self,
        *,
        socket: aiohttp.ClientWebSocketResponse,
        stream_name: str,
        expected_event_type: str,
        queue: StreamQueue,
    ) -> None:
        async for message in socket:
            if await self._is_cancelled(stream_name):
                break

            payload = self._parse_message(message)

            if payload is None:
                continue

            if payload.get("e") != expected_event_type:
                continue

            await queue.put(payload)

    @staticmethod
    def _put_stream_closed(
        queue: StreamQueue,
    ) -> None:
        """Place the terminal marker without blocking shutdown."""
        try:
            queue.put_nowait(_STREAM_CLOSED)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

            try:
                queue.put_nowait(_STREAM_CLOSED)
            except asyncio.QueueFull:
                pass

    async def _is_cancelled(
        self,
        stream_name: str,
    ) -> bool:
        """Return whether a stream was explicitly cancelled."""
        async with self._state_lock:
            return stream_name in self._cancelled_streams

    def _require_session(self) -> aiohttp.ClientSession:
        """Return the active session or raise RuntimeError."""
        session = self._session

        if session is None or session.closed:
            raise RuntimeError("Binance stream client is not connected")

        return session

    async def _register_socket(
        self,
        *,
        stream_name: str,
        socket: aiohttp.ClientWebSocketResponse,
    ) -> None:
        """Register an active stream socket."""
        async with self._state_lock:
            stream_sockets = self._active_sockets.setdefault(
                stream_name,
                set(),
            )
            stream_sockets.add(socket)

    async def _unregister_socket(
        self,
        *,
        stream_name: str,
        socket: aiohttp.ClientWebSocketResponse,
    ) -> None:
        """Remove a socket from the active registry."""
        async with self._state_lock:
            stream_sockets = self._active_sockets.get(stream_name)

            if stream_sockets is None:
                return

            stream_sockets.discard(socket)

            if not stream_sockets:
                del self._active_sockets[stream_name]

    async def _register_task(
        self,
        *,
        stream_name: str,
        task: StreamTask,
    ) -> None:
        """Register an active producer task."""
        async with self._state_lock:
            stream_tasks = self._stream_tasks.setdefault(
                stream_name,
                set(),
            )
            stream_tasks.add(task)

    async def _unregister_task(
        self,
        *,
        stream_name: str,
        task: StreamTask,
    ) -> None:
        """Remove a producer task from the active registry."""
        async with self._state_lock:
            stream_tasks = self._stream_tasks.get(stream_name)

            if stream_tasks is None:
                return

            stream_tasks.discard(task)

            if not stream_tasks:
                del self._stream_tasks[stream_name]

    def _build_stream_url(
        self,
        stream_name: str,
    ) -> str:
        """Build a Binance raw-stream WebSocket URL."""
        return f"{self._base_url}/ws/{stream_name}"

    @staticmethod
    def _parse_message(
        message: aiohttp.WSMessage,
    ) -> ExchangePayload | None:
        """Parse one WebSocket message into a mapping payload."""
        if message.type == aiohttp.WSMsgType.TEXT:
            raw_data = message.data

            if not isinstance(raw_data, str):
                raise ValueError("Binance WebSocket text message is invalid")

            try:
                payload: object = json.loads(raw_data)
            except json.JSONDecodeError as error:
                raise ValueError("Binance WebSocket returned invalid JSON") from error

            if not isinstance(payload, Mapping):
                raise ValueError("Binance WebSocket payload must be a mapping")

            return cast(ExchangePayload, payload)

        if message.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        }:
            raise RuntimeError("Binance WebSocket connection was closed")

        return None

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a Binance trading symbol."""
        normalized = symbol.strip().upper()

        if not normalized:
            raise ValueError("Trading symbol must not be empty")

        return normalized

    @staticmethod
    def _normalize_interval(
        interval: Interval,
    ) -> str:
        """Return the Binance stream value for an interval enum."""
        value = str(interval.value).strip()

        if not value:
            raise ValueError("Candle interval must not be empty")

        return value

    async def __aenter__(self) -> BinanceStreamClient:
        """Enter the asynchronous context manager."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        """Exit the asynchronous context manager."""
        del exc_type, exc_value, traceback
        await self.close()
