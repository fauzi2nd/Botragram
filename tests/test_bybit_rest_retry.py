"""
Botragram

Description:
    Bybit V5 REST retry policy and rate limit backoff tests.

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
import socket
from collections.abc import Awaitable, Callable
from typing import Final

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest
from aiohttp import web

# =============================================================================
# Local Imports
# =============================================================================
from botragram.exchanges.bybit.rest import (
    BybitRestClient,
    BybitRestResponseError,
)

type RequestHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]

_OK_PAYLOAD: Final[dict[str, object]] = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {"status": "success"},
}


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
async def test_bybit_rest_get_retries_on_rate_limit_and_succeeds() -> None:
    """Retry on Bybit retCode 10006 with backoff and return successful payload."""
    attempts = 0

    async def handler(_request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return web.json_response(
                {
                    "retCode": 10006,
                    "retMsg": "Too many visits. Exceeded the API Rate Limit.",
                },
                status=200,
            )
        return web.json_response(_OK_PAYLOAD, status=200)

    base_url, runner = await _start_server(handler)
    try:
        client = BybitRestClient(
            base_url=base_url,
            max_retries=2,
            retry_delay_seconds=0.01,
        )
        response = await client.get("/v5/market/kline")
        assert attempts == 2
        assert isinstance(response, dict)
        assert response.get("retCode") == 0
        await client.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_bybit_rest_get_exhausts_retries_on_persistent_rate_limit() -> None:
    """Raise BybitRestResponseError after exhausting all retries on retCode 10006."""
    attempts = 0

    async def handler(_request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        return web.json_response(
            {
                "retCode": 10006,
                "retMsg": "Too many visits. Exceeded the API Rate Limit.",
            },
            status=200,
        )

    base_url, runner = await _start_server(handler)
    try:
        client = BybitRestClient(
            base_url=base_url,
            max_retries=2,
            retry_delay_seconds=0.01,
        )
        with pytest.raises(BybitRestResponseError) as exc_info:
            await client.get("/v5/market/kline")

        assert attempts == 3  # initial attempt + 2 retries
        assert exc_info.value.ret_code == 10006
        await client.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_bybit_rest_get_retries_on_http_429_html_response() -> None:
    """Catch HTTP 429 HTML/non-JSON response, classify as 10006, and retry."""
    attempts = 0

    async def handler(_request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return web.Response(
                text="<html><body>Rate limited by Cloudflare</body></html>",
                status=429,
                content_type="text/html",
            )
        return web.json_response(_OK_PAYLOAD, status=200)

    base_url, runner = await _start_server(handler)
    try:
        client = BybitRestClient(
            base_url=base_url,
            max_retries=2,
            retry_delay_seconds=0.01,
        )
        response = await client.get("/v5/market/kline")
        assert attempts == 2
        assert isinstance(response, dict)
        assert response.get("retCode") == 0
        await client.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_bybit_rest_fails_immediately_on_non_retryable_error() -> None:
    """Do not retry non-transient business errors like 10002 Unauthorized."""
    attempts = 0

    async def handler(_request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        return web.json_response(
            {
                "retCode": 10002,
                "retMsg": "Invalid request, please check your timestamp",
            },
            status=200,
        )

    base_url, runner = await _start_server(handler)
    try:
        client = BybitRestClient(
            base_url=base_url,
            max_retries=2,
            retry_delay_seconds=0.01,
        )
        with pytest.raises(BybitRestResponseError) as exc_info:
            await client.get("/v5/market/kline")

        assert attempts == 1  # No retries for 10002
        assert exc_info.value.ret_code == 10002
        await client.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_bybit_rest_post_retries_on_rate_limit() -> None:
    """Ensure POST requests retry on rate limit 10006."""
    attempts = 0

    async def handler(_request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return web.json_response(
                {
                    "retCode": 10006,
                    "retMsg": "Too many visits",
                },
                status=200,
            )
        return web.json_response(_OK_PAYLOAD, status=200)

    base_url, runner = await _start_server(handler)
    try:
        client = BybitRestClient(
            base_url=base_url,
            max_retries=2,
            retry_delay_seconds=0.01,
        )
        response = await client.post("/v5/order/create", data={"symbol": "BTCUSDT"})
        assert attempts == 2
        assert isinstance(response, dict)
        assert response.get("retCode") == 0
        await client.close()
    finally:
        await runner.cleanup()
