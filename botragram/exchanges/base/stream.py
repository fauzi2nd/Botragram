"""
Botragram

Description:
    Base WebSocket stream client for real-time market data.

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
import logging
from typing import Any, Callable, Coroutine

# =============================================================================
# Third Party
# =============================================================================
import aiohttp

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.exchange import DEFAULT_WS_RECONNECT_DELAY_SECONDS

logger = logging.getLogger(__name__)

# Type alias for message callback listener
StreamCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


# =============================================================================
# Base WebSocket Stream Client Class
# =============================================================================
class BaseStreamClient:
    """Base WebSocket stream client for subscribing to real-time feeds."""

    def __init__(self, ws_url: str) -> None:
        """Initialize base WebSocket stream client.

        Args:
            ws_url: WebSocket server endpoint URL.
        """
        self._ws_url = ws_url
        self._is_running: bool = False
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._callbacks: list[StreamCallback] = []

    def add_callback(self, callback: StreamCallback) -> None:
        """Register a callback listener for incoming WebSocket messages.

        Args:
            callback: Async callback function accepting dict payload.
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    async def connect(self) -> None:
        """Establish WebSocket connection and start listening loop."""
        self._is_running = True
        self._session = aiohttp.ClientSession()

        while self._is_running:
            try:
                logger.info(f"Connecting to WebSocket stream: {self._ws_url}")
                async with self._session.ws_connect(self._ws_url) as ws:
                    self._ws = ws
                    logger.info("WebSocket connection established")
                    await self._listen_loop()
            except Exception as err:
                logger.error(f"WebSocket connection error: {err}")
                if self._is_running:
                    logger.info(
                        f"Reconnecting in {DEFAULT_WS_RECONNECT_DELAY_SECONDS}s..."
                    )
                    await asyncio.sleep(DEFAULT_WS_RECONNECT_DELAY_SECONDS)

    async def _listen_loop(self) -> None:
        """Listen loop for processing incoming WS frames."""
        if self._ws is None:
            return

        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = msg.json()
                await self._notify_callbacks(data)
            elif msg.type in (
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            ):
                logger.warning("WebSocket closed or encountered error")
                break

    async def _notify_callbacks(self, payload: dict[str, Any]) -> None:
        """Notify registered callback listeners with payload.

        Args:
            payload: JSON message payload.
        """
        for callback in self._callbacks:
            try:
                await callback(payload)
            except Exception as err:
                logger.error(f"Error in stream callback listener: {err}")

    async def disconnect(self) -> None:
        """Close WebSocket connection gracefully."""
        self._is_running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("WebSocket stream disconnected")
