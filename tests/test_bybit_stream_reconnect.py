"""
Botragram

Description:
    Tests for Bybit WebSocket streaming auto-reconnect and stream survival.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# =============================================================================
# Third-Party Imports
# =============================================================================
import aiohttp
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, LiveMarketStreamLifecycleStatus, StrategyType
from botragram.exchanges.bybit.mapper import BybitExchangeMapper
from botragram.exchanges.bybit.stream import BybitStreamClient
from botragram.models import (
    LiveMarketStreamIdentity,
    LiveRuntimePositionContext,
    Ticker,
)
from botragram.services.live_market_stream_service import LiveMarketStreamService


# =============================================================================
# Test Doubles
# =============================================================================
class MockBybitStreamClient(BybitStreamClient):
    """Test subclass exposing internal state safely for unit testing."""

    __test__ = False

    def set_session(self, session: aiohttp.ClientSession) -> None:
        """Inject a test session."""
        self._session = session

    def set_connected(self, connected: bool) -> None:
        """Inject a connected state."""
        self._connected = connected

    def is_topic_subscribed(self, topic: str) -> bool:
        """Inspect active subscriptions."""
        return topic in self._subscriptions

    async def subscribe_topic(self, topic: str) -> None:
        """Subscribe to a topic directly."""
        await self._subscribe(topic)


# =============================================================================
# Unit Tests
# =============================================================================
@pytest.mark.asyncio
async def test_bybit_stream_client_reconnects_and_resubscribes() -> None:
    """Ensure BybitStreamClient reconnects after disconnect and resubscribes topics."""
    mapper = BybitExchangeMapper()
    client = MockBybitStreamClient(
        websocket_url="wss://stream.bybit.com/v5/public/linear",
        mapper=mapper,
    )

    first_ws = MagicMock(spec=aiohttp.ClientWebSocketResponse)
    first_ws.closed = False
    first_ws.send_str = AsyncMock()
    first_ws.close = AsyncMock()

    first_disconnect_msg = MagicMock()
    first_disconnect_msg.type = aiohttp.WSMsgType.CLOSED
    first_ws.receive = AsyncMock(return_value=first_disconnect_msg)

    second_ws = MagicMock(spec=aiohttp.ClientWebSocketResponse)
    second_ws.closed = False
    second_ws.send_str = AsyncMock()
    second_ws.close = AsyncMock()

    ticker_msg = MagicMock()
    ticker_msg.type = aiohttp.WSMsgType.TEXT
    ticker_msg.data = json.dumps(
        {
            "topic": "tickers.BTCUSDT",
            "type": "snapshot",
            "data": {
                "symbol": "BTCUSDT",
                "lastPrice": "50000.0",
                "bid1Price": "49999.0",
                "ask1Price": "50001.0",
            },
        }
    )

    async def second_receive() -> Any:
        if not hasattr(second_receive, "called"):
            second_receive.called = True  # type: ignore[attr-defined]
            return ticker_msg
        await asyncio.sleep(3600)

    second_ws.receive = AsyncMock(side_effect=second_receive)

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.closed = False
    mock_session.close = AsyncMock()
    mock_session.ws_connect = AsyncMock(side_effect=[first_ws, second_ws])

    client.set_session(mock_session)

    await client.connect()
    assert client.is_connected
    assert mock_session.ws_connect.call_count == 1

    await client.subscribe_topic("tickers.BTCUSDT")
    assert client.is_topic_subscribed("tickers.BTCUSDT")

    # Wait for the first socket to hit CLOSED and trigger reconnection
    for _ in range(50):
        if mock_session.ws_connect.call_count >= 2 and client.is_connected:
            break
        await asyncio.sleep(0.05)

    assert mock_session.ws_connect.call_count >= 2
    assert client.is_connected

    second_calls = [
        call.args[0] for call in second_ws.send_str.call_args_list if call.args
    ]
    resub_found = any("tickers.BTCUSDT" in call_str for call_str in second_calls)
    assert resub_found

    await client.close()
    assert not client.is_connected


@pytest.mark.asyncio
async def test_bybit_stream_ticker_survives_reconnect() -> None:
    """Ensure stream_ticker async iterator does not abort during a reconnect."""
    mapper = BybitExchangeMapper()
    client = MockBybitStreamClient(
        websocket_url="wss://stream.bybit.com/v5/public/linear",
        mapper=mapper,
    )
    client.set_connected(True)

    collected_tickers: list[Ticker] = []

    async def consume() -> None:
        async for ticker in client.stream_ticker(symbol="BTCUSDT"):
            collected_tickers.append(ticker)
            if len(collected_tickers) == 2:
                break

    consumer_task = asyncio.create_task(consume())

    await asyncio.sleep(0.02)
    assert client.is_topic_subscribed("tickers.BTCUSDT")

    msg1 = json.dumps(
        {
            "topic": "tickers.BTCUSDT",
            "type": "snapshot",
            "data": {
                "symbol": "BTCUSDT",
                "lastPrice": "50000.0",
                "bid1Price": "49999.0",
                "ask1Price": "50001.0",
            },
        }
    )
    client.handle_message(msg1)
    await asyncio.sleep(0.02)
    assert len(collected_tickers) == 1
    assert collected_tickers[0].last_price == Decimal("50000.0")

    # Simulate temporary connection drop: _connected becomes False
    client.set_connected(False)
    await asyncio.sleep(0.02)

    assert not consumer_task.done()

    # Reconnected! Second tick arrives
    client.set_connected(True)
    msg2 = json.dumps(
        {
            "topic": "tickers.BTCUSDT",
            "type": "delta",
            "data": {
                "symbol": "BTCUSDT",
                "lastPrice": "50500.0",
            },
        }
    )
    client.handle_message(msg2)
    await asyncio.sleep(0.02)

    assert len(collected_tickers) == 2
    assert collected_tickers[1].last_price == Decimal("50500.0")
    await consumer_task

    await client.close()


@pytest.mark.asyncio
async def test_live_market_stream_service_replaces_failed_stream() -> None:
    """Ensure LiveMarketStreamService.start replaces a stream in FAILED status."""
    mock_market = MagicMock()
    mock_market.unsubscribe = AsyncMock()

    fail_trigger = asyncio.Event()

    async def mock_stream_ticker(*, symbol: str) -> AsyncIterator[Ticker]:
        if not fail_trigger.is_set():
            # First attempt fails immediately
            fail_trigger.set()
            raise RuntimeError("Stream broken")
        # Second attempt yields tick and stays active
        yield Ticker(
            symbol=symbol,
            last_price=Decimal("100"),
            bid_price=Decimal("99"),
            ask_price=Decimal("101"),
            timestamp=datetime.now(timezone.utc),
        )
        await asyncio.sleep(10)

    mock_market.stream_ticker = mock_stream_ticker

    service = LiveMarketStreamService(market_service=mock_market)
    context = LiveRuntimePositionContext(
        symbol="BTCUSDT",
        interval=Interval.M5,
        strategy_type=StrategyType.EMA_CROSS,
    )
    identity = LiveMarketStreamIdentity.from_runtime_context(context=context)

    # First start will fail
    await service.start(context=context)
    await fail_trigger.wait()
    await asyncio.sleep(0.05)

    failed_state = service.get_stream_state(identity=identity)
    assert failed_state is not None
    assert failed_state.lifecycle_status is LiveMarketStreamLifecycleStatus.FAILED
    assert failed_state.failure_type == "RuntimeError"

    # Second start on the failed stream should clean it up and restart it
    started_identity = await service.start(context=context)
    assert started_identity == identity

    is_ready = await service.wait_for_first_tick(identity=identity, timeout_seconds=2.0)
    assert is_ready

    active_state = service.get_stream_state(identity=identity)
    assert active_state is not None
    assert active_state.lifecycle_status is LiveMarketStreamLifecycleStatus.RUNNING
    assert active_state.first_tick_received

    await service.stop_all()
