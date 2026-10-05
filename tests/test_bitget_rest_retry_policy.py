"""Bitget transport safety regression tests with local HTTP boundaries."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from botragram.exceptions import ExchangeOrderOutcomeUnknownError
from botragram.exchanges.bitget.rest import BitgetRestClient, BitgetRestResponseError
from botragram.utils.connectivity import is_transient_connectivity_error

__all__: list[str] = []

type RequestHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@asynccontextmanager
async def local_client(
    handler: RequestHandler, *, retries: int = 2
) -> AsyncGenerator[BitgetRestClient, None]:
    """Own a loopback server and client without external network or credentials."""
    application = web.Application()
    application.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(application)
    await runner.setup()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        site = web.SockSite(runner, listener)
        await site.start()
        port = listener.getsockname()[1]
        client = BitgetRestClient(
            base_url=f"http://127.0.0.1:{port}",
            timeout_seconds=0.1,
            max_retries=retries,
            retry_delay_seconds=0,
        )
        try:
            yield client
        finally:
            await client.close()
            await runner.cleanup()


@pytest.mark.parametrize(
    "status,code",
    [
        (503, "PARSE_ERROR"),
        (429, "429"),
        (200, "40015"),
        (200, "40010"),
        (200, "40725"),
    ],
)
def test_classifier_recognizes_bitget_transient_failures(
    status: int, code: str
) -> None:
    """Allow bounded runtime recovery after a Bitget dependency outage."""
    error = BitgetRestResponseError(code=code, message="temporary", http_status=status)
    assert is_transient_connectivity_error(error)


@pytest.mark.parametrize("code", ["40009", "40014", "40017", "25202"])
def test_classifier_rejects_auth_permission_and_business_errors(code: str) -> None:
    """Do not retry deterministic Bitget rejections as connectivity outages."""
    error = BitgetRestResponseError(code=code, message="rejected", http_status=400)
    assert not is_transient_connectivity_error(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        '{"msg":"unavailable"}',
        '{"code":"00000"}',
        "[]",
        "<html>unavailable</html>",
        "null",
    ],
)
async def test_http_failure_never_becomes_success(body: str) -> None:
    """Reject HTTP failure regardless of vendor code or payload shape."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        return web.Response(text=body, status=503)

    async with local_client(handler) as client:
        with pytest.raises(BitgetRestResponseError) as raised:
            await client.get("/read")
    assert raised.value.http_status == 503
    assert attempts == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(503, "00000"), (429, "429"), (200, "40015")])
async def test_get_recovers_after_transient_response(status: int, code: str) -> None:
    """Retry reads until a successful response or the configured bound."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return web.json_response({"code": code}, status=status)
        return web.json_response({"code": "00000", "data": []})

    async with local_client(handler) as client:
        assert await client.get("/read") == {"code": "00000", "data": []}
    assert attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("client_oid", [False, True])
async def test_post_timeout_is_not_resubmitted(client_oid: bool) -> None:
    """A client ID alone must not authorize blind retry after an ambiguous POST."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.2)
        return web.json_response({"code": "00000"})

    async with local_client(handler) as client:
        data: dict[str, object] = {"symbol": "AUDIT"}
        if client_oid:
            data["clientOid"] = "audit-order"
        with pytest.raises(ExchangeOrderOutcomeUnknownError):
            await client.post("/order", data=data)
    assert attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "DELETE"])
@pytest.mark.parametrize(
    "status,body",
    [(503, '{"code":"00000"}'), (200, '{"code":"40015"}'), (200, "not-json")],
)
async def test_ambiguous_mutation_is_single_attempt(
    method: str, status: int, body: str
) -> None:
    """Surface uncertain mutations for reconciliation without automatic replay."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        return web.Response(text=body, status=status)

    async with local_client(handler) as client:
        with pytest.raises(ExchangeOrderOutcomeUnknownError):
            if method == "POST":
                await client.post("/order")
            else:
                await client.delete("/order")
    assert attempts == 1


@pytest.mark.asyncio
async def test_explicit_rejection_is_single_attempt() -> None:
    """Retain structured vendor rejection for existing high-level translators."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        return web.json_response({"code": "40014", "msg": "permission"}, status=403)

    async with local_client(handler) as client:
        with pytest.raises(BitgetRestResponseError) as raised:
            await client.post("/order")
    assert raised.value.code == "40014"
    assert attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["null", "42", '"invalid"'])
async def test_success_http_rejects_non_container_json(body: str) -> None:
    """Enforce the declared JSON response contract at the exchange boundary."""

    async def handler(request: web.Request) -> web.StreamResponse:
        return web.Response(text=body)

    async with local_client(handler) as client:
        with pytest.raises(BitgetRestResponseError):
            await client.get("/read")


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["40008", "40004"])
async def test_get_resynchronizes_expired_clock_before_retry(code: str) -> None:
    """Resign a safe read after one successful public clock synchronization."""
    paths: list[str] = []

    async def handler(request: web.Request) -> web.StreamResponse:
        paths.append(request.path)
        if len(paths) == 1:
            return web.json_response({"code": code})
        if request.path == "/api/v2/public/time":
            return web.json_response({"code": "00000", "data": {"serverTime": "1000"}})
        return web.json_response({"code": "00000"})

    async with local_client(handler) as client:
        assert await client.get("/read") == {"code": "00000"}
    assert paths == ["/read", "/api/v2/public/time", "/read"]


@pytest.mark.asyncio
async def test_clock_endpoint_does_not_recursively_resynchronize() -> None:
    """A failed public clock lookup must remain a bounded recovery failure."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        return web.json_response({"code": "40008"})

    async with local_client(handler) as client:
        with pytest.raises(BitgetRestResponseError):
            await client.synchronize_time()
    assert attempts == 1


@pytest.mark.asyncio
async def test_get_timeout_has_bounded_attempts() -> None:
    """Retry a read timeout only up to the configured transport budget."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.2)
        return web.json_response({"code": "00000"})

    async with local_client(handler) as client:
        with pytest.raises(TimeoutError):
            await client.get("/read")
    assert attempts == 3


@pytest.mark.asyncio
async def test_cancellation_propagates_without_retry() -> None:
    """Shutdown cancellation must not become a replayed mutation or read."""
    received = asyncio.Event()
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        received.set()
        await asyncio.sleep(0.2)
        return web.json_response({"code": "00000"})

    async with local_client(handler) as client:
        task = asyncio.create_task(client.post("/order"))
        await received.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert attempts == 1
