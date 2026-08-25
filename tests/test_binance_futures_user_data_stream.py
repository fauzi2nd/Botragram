"""Binance Futures private User Data Stream payload mapping tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import aiohttp
import pytest

from botragram.enums import OrderSide, OrderStatus, OrderType
from botragram.exchanges.binance.futures_user_data_stream import (
    BinanceFuturesUserDataStream,
)
from botragram.models import (
    FuturesUserDataAccountUpdate,
    FuturesUserDataAlgoUpdate,
    FuturesUserDataOrderUpdate,
)

_TIMESTAMP_MS = 1_756_080_000_000
_OBSERVED_AT = datetime.fromtimestamp(_TIMESTAMP_MS / 1_000, tz=UTC)


def test_maps_account_update_balance_and_position() -> None:
    """Map private account updates without exposing Binance payload mappings."""
    event = BinanceFuturesUserDataStream.map_account_update(
        payload={
            "E": _TIMESTAMP_MS,
            "a": {
                "B": [{"a": "USDT", "wb": "130.50", "cw": "125.50"}],
                "P": [
                    {
                        "s": "BTCUSDT",
                        "pa": "0.25",
                        "ep": "100000",
                        "up": "12.5",
                    }
                ],
            },
        }
    )

    assert isinstance(event, FuturesUserDataAccountUpdate)
    assert event.observed_at == _OBSERVED_AT
    assert event.balances[0].free == Decimal("125.50")
    assert event.balances[0].locked == Decimal("5.00")
    assert event.positions[0].symbol == "BTCUSDT"
    assert event.positions[0].quantity == Decimal("0.25")


def test_maps_order_trade_update_to_existing_order_model() -> None:
    """Map private order status updates to the immutable common Order model."""
    event = BinanceFuturesUserDataStream.map_order_update(
        payload={
            "E": _TIMESTAMP_MS,
            "o": {
                "i": 12345,
                "s": "BTCUSDT",
                "S": "SELL",
                "o": "STOP_MARKET",
                "X": "NEW",
                "q": "0.25",
                "z": "0",
                "p": "0",
                "sp": "95000",
                "T": _TIMESTAMP_MS,
                "c": "bsl-0123456789abcdef0123456789abcdef",
            },
        }
    )

    assert isinstance(event, FuturesUserDataOrderUpdate)
    assert event.order.order_id == "12345"
    assert event.order.side is OrderSide.SELL
    assert event.order.order_type is OrderType.STOP_MARKET
    assert event.order.status is OrderStatus.NEW
    assert event.order.stop_price == Decimal("95000")


def test_private_websocket_base_uses_binance_private_path() -> None:
    """Build the documented private endpoint from the public market endpoint."""
    assert (
        BinanceFuturesUserDataStream.build_private_websocket_base_url(
            "wss://fstream.binance.com/market"
        )
        == "wss://fstream.binance.com/private"
    )


def test_order_update_supports_valid_binance_conditional_order_values() -> None:
    """Keep valid account-wide trailing updates from terminating the stream."""
    event = BinanceFuturesUserDataStream.map_order_update(
        payload={
            "E": _TIMESTAMP_MS,
            "o": {
                "i": 12345,
                "s": "BTCUSDT",
                "S": "SELL",
                "o": "TRAILING_STOP_MARKET",
                "X": "EXPIRED_IN_MATCH",
                "q": "0.25",
                "z": "0",
                "p": "0",
                "sp": "0",
                "T": _TIMESTAMP_MS,
                "c": "external-order",
            },
        }
    )

    assert event.order.order_type is OrderType.TRAILING_STOP_MARKET
    assert event.order.status is OrderStatus.EXPIRED_IN_MATCH


def test_unsupported_order_update_does_not_terminate_private_stream() -> None:
    """Ignore an unknown external order kind without disconnecting the cache."""
    message = aiohttp.WSMessage(
        aiohttp.WSMsgType.TEXT,
        '{"e":"ORDER_TRADE_UPDATE","E":1756080000000,"o":{"o":"UNKNOWN"}}',
        "",
    )

    assert BinanceFuturesUserDataStream.parse_event(message) is None


def test_listen_key_expiry_forces_a_new_private_stream_session() -> None:
    """Never leave the cache READY after Binance ends a listen key."""
    message = aiohttp.WSMessage(
        aiohttp.WSMsgType.TEXT,
        '{"e":"listenKeyExpired","E":1756080000000}',
        "",
    )

    with pytest.raises(RuntimeError, match="listen key expired"):
        BinanceFuturesUserDataStream.parse_event(message)


def test_maps_algo_update_for_conditional_protection_observability() -> None:
    """Map Binance conditional SL/TP state without a REST dashboard request."""
    event = BinanceFuturesUserDataStream.map_algo_update(
        payload={
            "E": _TIMESTAMP_MS,
            "o": {
                "caid": "bsl-0123456789abcdef0123456789abcdef",
                "aid": 12345,
                "s": "BTCUSDT",
                "X": "TRIGGERING",
                "o": "STOP_MARKET",
                "tp": "95000",
            },
        }
    )

    assert isinstance(event, FuturesUserDataAlgoUpdate)
    assert event.client_algo_id.startswith("bsl-")
    assert event.status.value == "triggering"
    assert event.order_type is OrderType.STOP_MARKET
    assert event.trigger_price == Decimal("95000")


@dataclass(slots=True)
class _IdleSocket:
    """Keep one private WebSocket session open without account events."""

    closed: bool = False

    def __aiter__(self) -> AsyncIterator[aiohttp.WSMessage]:
        """Return this idle socket as an async message iterator."""
        return self

    async def __anext__(self) -> aiohttp.WSMessage:
        """Wait indefinitely to emulate a healthy but idle account stream."""
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        """Close the idle socket."""
        self.closed = True


@dataclass(slots=True)
class _PrivateStreamSession:
    """Capture private WebSocket connection options without network I/O."""

    socket: _IdleSocket
    options: dict[str, object] = field(default_factory=dict)
    closed: bool = False

    async def ws_connect(
        self,
        url: str,
        **options: object,
    ) -> _IdleSocket:
        """Record the requested options and return one idle socket."""
        self.options = {"url": url, **options}
        return self.socket

    async def close(self) -> None:
        """Close the fake session."""
        self.closed = True


@dataclass(slots=True)
class _PrivateStreamRest:
    """Provide one listen key and record cleanup without transport I/O."""

    close_calls: int = 0

    async def start_user_data_stream(self, *, path: str) -> str:
        """Return one opaque test listen key."""
        assert path == "/fapi/v1/listenKey"
        return "listen-key"

    async def close_user_data_stream(self, *, path: str) -> None:
        """Record one exact listen-key cleanup call."""
        assert path == "/fapi/v1/listenKey"
        self.close_calls += 1


def test_idle_private_socket_uses_heartbeat_without_receive_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep an idle User Data Stream open instead of reconnecting each minute."""
    asyncio.run(_run_idle_private_socket_test(monkeypatch=monkeypatch))


async def _run_idle_private_socket_test(*, monkeypatch: pytest.MonkeyPatch) -> None:
    """Open the stream through a fake session and inspect connection options."""
    socket = _IdleSocket()
    session = _PrivateStreamSession(socket=socket)
    rest = _PrivateStreamRest()
    monkeypatch.setattr(
        "botragram.exchanges.binance.futures_user_data_stream.aiohttp.ClientSession",
        lambda: session,
    )
    stream = BinanceFuturesUserDataStream(
        rest=rest,
        websocket_base_url="wss://fstream.binance.com/market",
    )
    events = stream.stream_events()

    event = await anext(events)

    assert event.observed_at.tzinfo is UTC
    assert session.options["receive_timeout"] is None
    assert session.options["heartbeat"] == 30.0
    await events.aclose()
    assert socket.closed
    assert rest.close_calls == 1
