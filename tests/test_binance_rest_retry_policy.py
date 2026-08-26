"""Binance REST retry-policy regression tests."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from time import monotonic

import pytest
from aiohttp import web

from botragram.enums import OrderSide, OrderType
from botragram.exceptions import (
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.base.rest import JsonObject
from botragram.exchanges.binance.futures_client import (
    BinanceFuturesExchangeClient,
)
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import (
    BinanceRateLimitGovernor,
    BinanceRestClient,
    BinanceRestResponseError,
)

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
async def test_time_synchronization_offsets_authenticated_signatures() -> None:
    """Use the midpoint-adjusted server clock for signed request timestamps."""
    request_timestamp: str | None = None
    clock_values = iter((1_000, 1_100, 1_200))

    async def handler(request: web.Request) -> web.StreamResponse:
        """Serve a deterministic server time then observe one signed request."""
        nonlocal request_timestamp
        if request.path == "/fapi/v1/time":
            return web.json_response({"serverTime": 3_050})

        request_timestamp = request.query["timestamp"]
        return web.json_response({"ok": True})

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(
        base_url=base_url,
        api_key="key",
        api_secret="secret",
        clock_ms=lambda: next(clock_values),
    )

    try:
        await rest.synchronize_time(path="/fapi/v1/time")
        assert await rest.get("/signed", authenticated=True) == {"ok": True}
    finally:
        await rest.close()
        await runner.cleanup()

    assert request_timestamp == "3200"


@pytest.mark.asyncio
async def test_time_synchronization_rejects_invalid_server_timestamp() -> None:
    """Fail closed instead of signing requests against an unproven server clock."""

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return a malformed public server-time payload."""
        del request
        return web.json_response({"serverTime": "invalid"})

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(base_url=base_url)

    try:
        with pytest.raises(RuntimeError, match="server time response is invalid"):
            await rest.synchronize_time(path="/fapi/v1/time")
    finally:
        await rest.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_get_rate_limit_honors_retry_after_before_retrying() -> None:
    """Wait for Binance's requested delay before repeating a safe read."""
    attempts = 0
    request_times: list[float] = []

    async def handler(request: web.Request) -> web.StreamResponse:
        """Rate limit once before accepting the GET request."""
        nonlocal attempts
        del request
        attempts += 1
        request_times.append(monotonic())

        if attempts == 1:
            return web.json_response(
                {"code": -1003, "msg": "too many requests"},
                status=429,
                headers={"Retry-After": "0.03"},
            )

        return web.json_response({"ok": True})

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(
        base_url=base_url,
        max_retries=3,
        retry_delay_seconds=0,
    )

    try:
        assert await rest.get("/read") == {"ok": True}
    finally:
        await rest.close()
        await runner.cleanup()

    assert attempts == 2
    assert request_times[1] - request_times[0] >= 0.025


@pytest.mark.asyncio
async def test_response_headers_and_exchange_info_drive_discovery_throttle() -> None:
    """Use authoritative Binance limits and usage headers for headroom gating."""
    requests = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return exact request and order limits with threshold usage."""
        nonlocal requests
        del request
        requests += 1
        return web.json_response(
            {
                "rateLimits": [
                    {
                        "rateLimitType": "REQUEST_WEIGHT",
                        "interval": "MINUTE",
                        "intervalNum": 1,
                        "limit": 1_000,
                    },
                    {
                        "rateLimitType": "ORDERS",
                        "interval": "SECOND",
                        "intervalNum": 10,
                        "limit": 100,
                    },
                ]
            },
            headers={
                "X-MBX-USED-WEIGHT-1M": "750",
                "X-MBX-ORDER-COUNT-10S": "75",
            },
        )

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(base_url=base_url)

    try:
        await rest.get("/fapi/v1/exchangeInfo")
        snapshot = rest.rate_limit_governor.get_snapshot()
    finally:
        await rest.close()
        await runner.cleanup()

    windows = {
        (window.rate_limit_type, window.interval_seconds): window
        for window in snapshot.windows
    }
    assert snapshot.discovery_throttled
    assert snapshot.throttle_reason == "ORDERS:10s"
    assert snapshot.throttle_percent == 75
    assert windows[("ORDERS", 10)].usage_percent == 75
    assert windows[("REQUEST_WEIGHT", 60)].limit == 1_000
    assert windows[("REQUEST_WEIGHT", 60)].used == 750
    assert requests == 1


def test_governor_expires_usage_and_honors_retry_after_without_network() -> None:
    """Resume discovery only after both observed windows and cooldown expire."""
    now = [100.0]
    governor = BinanceRateLimitGovernor(clock=lambda: now[0])
    payload: JsonObject = {
        "rateLimits": [
            {
                "rateLimitType": "REQUEST_WEIGHT",
                "interval": "MINUTE",
                "intervalNum": 1,
                "limit": 100,
            }
        ]
    }
    governor.observe_payload(payload=payload)
    governor.observe_response(
        headers={"X-MBX-USED-WEIGHT-1M": "74"},
        status=200,
        retry_after_seconds=None,
    )

    assert governor.should_throttle_discovery() is False

    governor.observe_response(
        headers={"X-MBX-USED-WEIGHT-1M": "75"},
        status=429,
        retry_after_seconds=10,
    )
    blocked = governor.get_snapshot()
    assert blocked.discovery_throttled
    assert blocked.throttle_reason == "retry_after"
    assert blocked.retry_after_seconds == 10

    now[0] = 111.0
    assert governor.should_throttle_discovery()

    now[0] = 161.0
    resumed = governor.get_snapshot()
    assert resumed.discovery_throttled is False
    assert resumed.windows == ()


def test_governor_concurrent_updates_keep_highest_active_usage() -> None:
    """Serialize concurrent response updates without losing high-water usage."""
    governor = BinanceRateLimitGovernor()
    payload: JsonObject = {
        "rateLimits": [
            {
                "rateLimitType": "REQUEST_WEIGHT",
                "interval": "MINUTE",
                "intervalNum": 1,
                "limit": 1_000,
            }
        ]
    }
    governor.observe_payload(payload=payload)

    def observe(used: int) -> None:
        governor.observe_response(
            headers={"X-MBX-USED-WEIGHT-1M": str(used)},
            status=200,
            retry_after_seconds=None,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        tuple(executor.map(observe, range(900, -1, -1)))

    snapshot = governor.get_snapshot()
    assert len(snapshot.windows) == 1
    assert snapshot.windows[0].used == 900
    assert snapshot.discovery_throttled


def test_missing_and_malformed_headers_leave_valid_budget_observation_intact() -> None:
    """Ignore incomplete telemetry conservatively without raising or erasing state."""
    governor = BinanceRateLimitGovernor()
    governor.observe_response(
        headers={"X-MBX-USED-WEIGHT-1M": "1200"},
        status=200,
        retry_after_seconds=None,
    )
    governor.observe_response(
        headers={
            "X-MBX-USED-WEIGHT-1M": "not-an-integer",
            "X-MBX-USED-WEIGHT-0M": "2000",
            "unrelated": "value",
        },
        status=200,
        retry_after_seconds=None,
    )
    governor.observe_response(
        headers={},
        status=200,
        retry_after_seconds=None,
    )

    snapshot = governor.get_snapshot()
    assert len(snapshot.windows) == 1
    assert snapshot.windows[0].used == 1200
    assert snapshot.discovery_throttled is False


@pytest.mark.parametrize("status", [418, 429])
def test_rate_limit_status_blocks_only_optional_budget(status: int) -> None:
    """Treat bans and throttles as optional-work cooldowns without sleeping."""
    now = [50.0]
    governor = BinanceRateLimitGovernor(clock=lambda: now[0])

    governor.observe_response(
        headers={},
        status=status,
        retry_after_seconds=12,
    )

    snapshot = governor.get_snapshot()
    assert snapshot.discovery_throttled
    assert snapshot.throttle_reason == "retry_after"
    assert snapshot.retry_after_seconds == 12
    now[0] = 63.0
    assert governor.should_throttle_discovery() is False


def test_governor_logs_only_throttle_transitions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Expose budget context once per state transition without cycle spam."""
    now = [100.0]
    governor = BinanceRateLimitGovernor(clock=lambda: now[0])
    caplog.set_level(logging.INFO, logger="botragram.exchanges.binance.rest")

    governor.observe_response(
        headers={"X-MBX-USED-WEIGHT-1M": "1800"},
        status=200,
        retry_after_seconds=None,
    )
    governor.get_snapshot()
    governor.get_snapshot()
    now[0] = 161.0
    governor.get_snapshot()
    governor.get_snapshot()

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert "used=1800 limit=2400" in messages[0]
    assert "threshold_pct=75 headroom=600" in messages[0]
    assert "resumed" in messages[1]


@pytest.mark.asyncio
async def test_get_client_error_is_not_retried() -> None:
    """Do not waste API quota retrying a deterministic client rejection."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return an invalid-credential rejection once."""
        nonlocal attempts
        del request
        attempts += 1
        return web.json_response(
            {"code": -2015, "msg": "invalid credentials"},
            status=401,
        )

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(
        base_url=base_url,
        max_retries=3,
        retry_delay_seconds=0,
    )

    try:
        with pytest.raises(BinanceRestResponseError, match="status=401"):
            await rest.get("/read")
    finally:
        await rest.close()
        await runner.cleanup()

    assert attempts == 1


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
        with pytest.raises(ExchangeOrderOutcomeUnknownError):
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
async def test_futures_entry_post_explicit_rejection_is_typed() -> None:
    """Translate Binance's explicit entry rejection at the Futures boundary."""
    attempts = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        """Return one Binance-defined invalid-order response."""
        nonlocal attempts
        attempts += 1
        return web.json_response({"code": -2010, "msg": "rejected"}, status=400)

    base_url, runner = await _start_server(handler)
    rest = BinanceRestClient(base_url=base_url, api_key="key", api_secret="secret")
    client = BinanceFuturesExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    try:
        with pytest.raises(ExchangeOrderRejectedError):
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
        with pytest.raises(ExchangeOrderOutcomeUnknownError):
            await client.create_protection_orders(
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                quantity=Decimal("0.01"),
                stop_loss=Decimal("64000"),
                stop_loss_client_algo_id="bsl-00000000000000000000000000000000",
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
