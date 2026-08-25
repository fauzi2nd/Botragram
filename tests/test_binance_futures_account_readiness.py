"""Binance Futures account-readiness regression tests."""

from __future__ import annotations

import socket
from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from aiohttp import web

from botragram.exchanges.binance.futures_client import BinanceFuturesExchangeClient
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient

__all__ = []

type RequestHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _account_configuration(**overrides: bool) -> dict[str, bool]:
    """Build one supported Binance Futures account configuration."""
    configuration = {
        "canTrade": True,
        "dualSidePosition": False,
        "multiAssetsMargin": False,
    }
    configuration.update(overrides)
    return configuration


async def _start_server(handler: RequestHandler) -> tuple[str, web.AppRunner]:
    """Start one deterministic local HTTP server."""
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
async def test_futures_mainnet_readiness_synchronizes_server_clock() -> None:
    """Fetch the official Futures server clock before MAINNET runtime starts."""
    requested_paths: list[str] = []

    async def handler(request: web.Request) -> web.StreamResponse:
        """Record the time and mode endpoints used by MAINNET readiness."""
        requested_paths.append(request.path)
        if request.path == "/fapi/v1/time":
            return web.json_response({"serverTime": 1_700_000_000_000})
        return web.json_response(_account_configuration())

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(base_url=base_url, api_key="key", api_secret="secret")
    client = BinanceFuturesExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    try:
        await client.verify_mainnet_readiness()
    finally:
        await rest.close()
        await runner.cleanup()

    assert requested_paths == ["/fapi/v1/time", "/fapi/v1/accountConfig"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"canTrade": False}, "not permitted to trade"),
        ({"dualSidePosition": True}, "Hedge Mode is unsupported"),
        ({"multiAssetsMargin": True}, "Multi-Assets Mode is unsupported"),
    ],
)
async def test_futures_mainnet_readiness_rejects_unsupported_account_config(
    overrides: dict[str, bool],
    message: str,
) -> None:
    """Fail closed for every unsupported account-level execution mode."""

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return clock and one explicitly unsafe account configuration."""
        if request.path == "/fapi/v1/time":
            return web.json_response({"serverTime": 1_700_000_000_000})
        return web.json_response(_account_configuration(**overrides))

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(base_url=base_url, api_key="key", api_secret="secret")
    client = BinanceFuturesExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    try:
        with pytest.raises(RuntimeError, match=message):
            await client.verify_mainnet_readiness()
    finally:
        await rest.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_futures_mainnet_symbol_readiness_accepts_safe_existing_config() -> None:
    """Accept isolated, bounded-leverage symbol state without mutating it."""
    methods: list[str] = []

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return one safe authenticated symbol configuration."""
        methods.append(request.method)
        assert request.path == "/fapi/v1/symbolConfig"
        assert request.query["symbol"] == "BTCUSDT"
        return web.json_response(
            [
                {
                    "symbol": "BTCUSDT",
                    "marginType": "ISOLATED",
                    "isAutoAddMargin": False,
                    "leverage": 2,
                    "maxNotionalValue": "100000",
                }
            ]
        )

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(base_url=base_url, api_key="key", api_secret="secret")
    client = BinanceFuturesExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    try:
        await client.verify_mainnet_symbol_readiness(
            symbol="btcusdt",
            maximum_leverage=2,
            entry_notional=Decimal("1000"),
        )
    finally:
        await rest.close()
        await runner.cleanup()

    assert methods == ["GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"marginType": "CROSSED"}, "requires isolated margin"),
        ({"isAutoAddMargin": True}, "must be disabled"),
        ({"leverage": 3}, "exceeds the risk limit"),
        ({"maxNotionalValue": "999"}, "below the entry"),
    ],
)
async def test_futures_mainnet_symbol_readiness_rejects_unsafe_config(
    override: dict[str, str | int | bool],
    message: str,
) -> None:
    """Reject unsafe existing symbol settings using GET-only evidence."""

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return one explicitly unsafe symbol configuration."""
        configuration: dict[str, str | int | bool] = {
            "symbol": "BTCUSDT",
            "marginType": "ISOLATED",
            "isAutoAddMargin": False,
            "leverage": 2,
            "maxNotionalValue": "100000",
        }
        configuration.update(override)
        return web.json_response([configuration])

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(base_url=base_url, api_key="key", api_secret="secret")
    client = BinanceFuturesExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    try:
        with pytest.raises(RuntimeError, match=message):
            await client.verify_mainnet_symbol_readiness(
                symbol="BTCUSDT",
                maximum_leverage=2,
                entry_notional=Decimal("1000"),
            )
    finally:
        await rest.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_futures_readiness_accepts_one_way_position_mode() -> None:
    """Accept an authenticated Binance position-mode response set to one-way."""

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return the one-way mode payload expected by the Futures client."""
        assert request.path == "/fapi/v1/positionSide/dual"
        assert request.headers["X-MBX-APIKEY"] == "key"
        assert "signature" in request.query
        return web.json_response({"dualSidePosition": False})

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(base_url=base_url, api_key="key", api_secret="secret")
    client = BinanceFuturesExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    try:
        await client.verify_one_way_position_mode()
    finally:
        await rest.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_futures_readiness_rejects_hedge_position_mode() -> None:
    """Fail closed instead of assigning one-way semantics to a hedge account."""

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return the explicit Binance Hedge Mode state."""
        del request
        return web.json_response({"dualSidePosition": True})

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(base_url=base_url, api_key="key", api_secret="secret")
    client = BinanceFuturesExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    try:
        with pytest.raises(RuntimeError, match="Hedge Mode is unsupported"):
            await client.verify_one_way_position_mode()
    finally:
        await rest.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_futures_readiness_rejects_invalid_position_mode_response() -> None:
    """Reject an unproven Binance account mode response before runtime starts."""

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return a malformed Futures position-mode payload."""
        del request
        return web.json_response({"dualSidePosition": "false"})

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(base_url=base_url, api_key="key", api_secret="secret")
    client = BinanceFuturesExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    try:
        with pytest.raises(RuntimeError, match="position mode response is invalid"):
            await client.verify_one_way_position_mode()
    finally:
        await rest.close()
        await runner.cleanup()
