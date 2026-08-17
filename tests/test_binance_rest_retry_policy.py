"""Binance REST retry-policy regression tests."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from aiohttp import web

from botragram.enums import OrderSide, OrderType
from botragram.exchanges.binance.futures_client import (
    BinanceFuturesExchangeClient,
)
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient

type RequestHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


async def _start_server(handler: RequestHandler) -> tuple[str, web.AppRunner]:
    """Start one local deterministic HTTP server."""
    application = web.Application()
    application.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(application)
    await runner.setup()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen()
    site = web.SockSite(runner, server_socket)
    await site.start()
    port = server_socket.getsockname()[1]
    return f"http://127.0.0.1:{port}", runner


@pytest.mark.asyncio
async def test_authenticated_get_retries_with_fresh_signature_parameters() -> None:
    """Keep bounded read retries while rebuilding Binance auth each attempt."""
    attempts = 0
    timestamps: list[str] = []
    signatures: list[str] = []

    async def handler(request: web.Request) -> web.StreamResponse:
        """Fail once, then return a successful read payload."""
        nonlocal attempts
        attempts += 1
        timestamps.append(request.query["timestamp"])
        signatures.append(request.query["signature"])

        if attempts == 1:
            return web.json_response({"code": -1000, "msg": "temporary"}, status=500)

        return web.json_response({"ok": True})

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(
        base_url=base_url,
        api_key="key",
        api_secret="secret",
        max_retries=3,
        retry_delay_seconds=0.01,
    )

    try:
        assert await rest.get("/read", authenticated=True) == {"ok": True}
    finally:
        await rest.close()
        await runner.cleanup()

    assert attempts == 2
    assert timestamps[0] != timestamps[1]
    assert signatures[0] != signatures[1]


@pytest.mark.asyncio
async def test_futures_entry_post_timeout_is_single_attempt() -> None:
    """Prevent a lost entry response from causing a duplicate POST submission."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        """Receive the order before exceeding the client timeout."""
        nonlocal attempts
        assert request.method == "POST"
        assert request.path == "/fapi/v1/order"
        attempts += 1
        await asyncio.sleep(0.05)
        return web.json_response({})

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(
        base_url=base_url,
        api_key="key",
        api_secret="secret",
        request_timeout_seconds=0.01,
        max_retries=3,
        retry_delay_seconds=0,
    )
    client = BinanceFuturesExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    try:
        with pytest.raises(TimeoutError):
            await client.create_order(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.01"),
            )
    finally:
        await rest.close()
        await runner.cleanup()

    assert attempts == 1


@pytest.mark.asyncio
async def test_futures_protection_post_timeout_is_single_attempt() -> None:
    """Prevent an ambiguous protection POST from creating a duplicate leg."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        """Receive one protection request before timing out its response."""
        nonlocal attempts
        assert request.method == "POST"
        assert request.path == "/fapi/v1/algoOrder"
        attempts += 1
        await asyncio.sleep(0.05)
        return web.json_response({})

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(
        base_url=base_url,
        api_key="key",
        api_secret="secret",
        request_timeout_seconds=0.01,
        max_retries=3,
        retry_delay_seconds=0,
    )
    client = BinanceFuturesExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    try:
        with pytest.raises(TimeoutError):
            await client.create_protection_orders(
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                quantity=Decimal("0.01"),
                stop_loss=Decimal("64000"),
            )
    finally:
        await rest.close()
        await runner.cleanup()

    assert attempts == 1


@pytest.mark.asyncio
async def test_delete_failure_is_single_attempt() -> None:
    """Keep ambiguous cancellation mutations conservative until reconciliation."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return one transient-looking failure for the cancellation request."""
        nonlocal attempts
        assert request.method == "DELETE"
        attempts += 1
        return web.json_response({"code": -1000, "msg": "temporary"}, status=500)

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(
        base_url=base_url,
        max_retries=3,
        retry_delay_seconds=0,
    )

    try:
        with pytest.raises(RuntimeError, match="status=500"):
            await rest.delete("/fapi/v1/order")
    finally:
        await rest.close()
        await runner.cleanup()

    assert attempts == 1
