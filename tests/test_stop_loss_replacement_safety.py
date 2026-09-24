"""
Botragram

Description:
    Regression tests verifying stop loss replacement is strictly new-stop-first
    and cancellation failures are not silently swallowed.

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
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OrderSide
from botragram.exceptions import (
    ExchangeError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.base.rest import (
    JsonResponse,
    QueryParams,
    RequestHeaders,
)
from botragram.exchanges.bitget.cfd_client import BitgetCfdExchangeClient
from botragram.exchanges.bitget.cfd_mapper import BitgetCfdMapper
from botragram.exchanges.bitget.futures_client import BitgetFuturesExchangeClient
from botragram.exchanges.bitget.mapper import BitgetExchangeMapper
from botragram.exchanges.bitget.rest import BitgetRestClient, BitgetRestResponseError
from botragram.exchanges.bybit.futures_client import BybitFuturesExchangeClient
from botragram.exchanges.bybit.mapper import BybitExchangeMapper
from botragram.exchanges.bybit.rest import BybitRestClient, BybitRestResponseError


# =============================================================================
# Mock Transports
# =============================================================================
class MockBitgetRest(BitgetRestClient):
    """Mock Bitget REST transport with deterministic endpoint handlers."""

    def __init__(self) -> None:
        super().__init__(
            base_url="https://api.bitget.com",
            api_key="key",
            api_secret="secret",
            passphrase="pass",
        )
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []
        self.place_response: JsonResponse | Exception = {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "orderId": "order_new_123",
                    "clientOid": "stop_new_algo",
                    "symbol": "BTCUSDT",
                    "planType": "loss_plan",
                    "triggerPrice": "60000",
                    "size": "0.1",
                    "side": "sell",
                    "status": "not_trigger",
                }
            ],
        }
        self.cancel_response: JsonResponse | Exception = {
            "code": "00000",
            "msg": "success",
            "data": {},
        }
        self.open_orders_response: JsonResponse = {
            "code": "00000",
            "msg": "success",
            "data": [],
        }

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        del headers, authenticated
        self.calls.append(("GET", path, dict(params) if params else None))
        return self._validate_response_envelope(self.open_orders_response)

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: dict[str, object] | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        del headers, authenticated, params
        self.calls.append(("POST", path, data))
        if "place" in path:
            if isinstance(self.place_response, Exception):
                raise self.place_response
            return self._validate_response_envelope(self.place_response)
        if "cancel" in path:
            if isinstance(self.cancel_response, Exception):
                raise self.cancel_response
            return self._validate_response_envelope(self.cancel_response)
        return self._validate_response_envelope(
            {"code": "00000", "msg": "success", "data": {}}
        )


class MockBybitRest(BybitRestClient):
    """Mock Bybit REST transport with deterministic endpoint handlers."""

    def __init__(self) -> None:
        super().__init__(
            base_url="https://api-testnet.bybit.com",
            api_key="key",
            api_secret="secret",
        )
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []
        self.place_response: JsonResponse | Exception = {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "orderId": "bybit_new_123",
                "orderLinkId": "bybit_stop_new",
            },
        }
        self.cancel_response: JsonResponse | Exception = {
            "retCode": 0,
            "retMsg": "OK",
            "result": {},
        }
        self.open_orders_list: list[object] = []

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        del headers, authenticated
        self.calls.append(("GET", path, dict(params) if params else None))
        return {
            "retCode": 0,
            "retMsg": "OK",
            "result": {"list": self.open_orders_list},
        }

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: dict[str, object] | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        del headers, authenticated, params
        self.calls.append(("POST", path, data))
        if "/order/create" in path:
            if isinstance(self.place_response, Exception):
                raise self.place_response
            return self.place_response
        if "/order/cancel" in path:
            if isinstance(self.cancel_response, Exception):
                raise self.cancel_response
            return self.cancel_response
        return {"retCode": 0, "retMsg": "OK", "result": {}}


# =============================================================================
# Bitget Futures Tests
# =============================================================================
@pytest.mark.asyncio
async def test_bitget_futures_ensure_stop_success_cancels_old_after_new() -> None:
    """Successful replacement places new stop FIRST, then cancels predecessor."""
    rest = MockBitgetRest()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    order = await client.ensure_stop_loss_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("0.1"),
        stop_loss=Decimal("60000"),
        client_algo_id="stop_new_algo",
        previous_client_algo_id="stop_old_algo",
    )

    assert order.client_order_id == "stop_new_algo"
    assert order.stop_price == Decimal("60000")

    place_calls = [
        c for c in rest.calls if c[1] == "/api/v3/trade/place-strategy-order"
    ]
    cancel_calls = [
        c for c in rest.calls if c[1] == "/api/v3/trade/cancel-strategy-order"
    ]
    assert len(place_calls) == 1
    assert len(cancel_calls) == 1
    # Place must happen before cancel
    assert rest.calls.index(place_calls[0]) < rest.calls.index(cancel_calls[0])


@pytest.mark.asyncio
async def test_bitget_futures_ensure_stop_failure_leaves_old_stop_untouched() -> None:
    """If new stop placement fails, predecessor stop must NOT be cancelled."""
    rest = MockBitgetRest()
    rest.place_response = BitgetRestResponseError(
        code="22002", message="Trigger price invalid", http_status=200
    )
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    with pytest.raises(ExchangeOrderRejectedError):
        await client.ensure_stop_loss_order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("0.1"),
            stop_loss=Decimal("60000"),
            client_algo_id="stop_new_algo",
            previous_client_algo_id="stop_old_algo",
        )

    cancel_calls = [
        c for c in rest.calls if c[1] == "/api/v3/trade/cancel-strategy-order"
    ]
    assert len(cancel_calls) == 0


@pytest.mark.asyncio
async def test_bitget_futures_ensure_stop_timeout_leaves_old_stop_untouched() -> None:
    """If new stop placement times out, predecessor stop must NOT be cancelled."""
    rest = MockBitgetRest()
    rest.place_response = TimeoutError("Connection timed out to Bitget")
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    with pytest.raises(ExchangeOrderOutcomeUnknownError):
        await client.ensure_stop_loss_order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("0.1"),
            stop_loss=Decimal("60000"),
            client_algo_id="stop_new_algo",
            previous_client_algo_id="stop_old_algo",
        )

    cancel_calls = [
        c for c in rest.calls if c[1] == "/api/v3/trade/cancel-strategy-order"
    ]
    assert len(cancel_calls) == 0


@pytest.mark.asyncio
async def test_bitget_futures_cancel_protection_failure_propagates_error() -> None:
    """If canceling predecessor fails, error must be propagated, not swallowed."""
    rest = MockBitgetRest()
    rest.cancel_response = ConnectionError("Network reset during cancel")
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    with pytest.raises(ExchangeOrderOutcomeUnknownError, match="outcome is unknown"):
        await client.ensure_stop_loss_order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("0.1"),
            stop_loss=Decimal("60000"),
            client_algo_id="stop_new_algo",
            previous_client_algo_id="stop_old_algo",
        )


@pytest.mark.asyncio
async def test_bitget_futures_ensure_stop_idempotent_when_already_active() -> None:
    """If stop with client_algo_id is already active, no new order is placed."""
    rest = MockBitgetRest()
    rest.open_orders_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "orderId": "order_existing_123",
                "clientOid": "stop_new_algo",
                "symbol": "BTCUSDT",
                "planType": "loss_plan",
                "triggerPrice": "60000",
                "size": "0.1",
                "side": "sell",
                "status": "not_trigger",
            }
        ],
    }
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    order = await client.ensure_stop_loss_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("0.1"),
        stop_loss=Decimal("60000"),
        client_algo_id="stop_new_algo",
        previous_client_algo_id="stop_new_algo",
    )

    assert order.client_order_id == "stop_new_algo"
    assert order.stop_price == Decimal("60000")
    place_calls = [c for c in rest.calls if c[1] == "/api/v3/trade/place-plan-order"]
    cancel_calls = [c for c in rest.calls if c[1] == "/api/v3/trade/cancel-plan-order"]
    assert len(place_calls) == 0
    assert len(cancel_calls) == 0


# =============================================================================
# Bitget CFD Tests
# =============================================================================
@pytest.mark.asyncio
async def test_bitget_cfd_ensure_stop_new_stop_first_and_cancel_failure() -> None:
    """Bitget CFD ensures new stop first and propagates cancel failure."""
    rest = MockBitgetRest()
    rest.place_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "orderId": "cfd_order_123",
                "clientOid": "cfd_stop_new",
                "symbol": "XAUUSD",
                "planType": "loss_plan",
                "triggerPrice": "2600",
                "size": "0.1",
                "side": "sell",
                "status": "not_trigger",
            }
        ],
    }
    rest.cancel_response = BitgetRestResponseError(
        code="50001", message="Server error on cancel", http_status=500
    )
    client = BitgetCfdExchangeClient(
        rest=rest,
        mapper=BitgetCfdMapper(),
        mode="ecn",
    )

    with pytest.raises(ExchangeError, match="Failed to cancel CFD protection order"):
        await client.ensure_stop_loss_order(
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=Decimal("0.1"),
            stop_loss=Decimal("2600"),
            client_algo_id="cfd_stop_new",
            previous_client_algo_id="cfd_stop_old",
        )

    place_calls = [
        c for c in rest.calls if c[1] == "/api/v3/cfd/trade/place-strategy-order"
    ]
    assert len(place_calls) == 1


# =============================================================================
# Bybit Futures Tests
# =============================================================================
@pytest.mark.asyncio
async def test_bybit_ensure_stop_new_stop_first_and_error_propagation() -> None:
    """Bybit futures ensures new stop first and does not swallow cancel errors."""
    rest = MockBybitRest()
    rest.cancel_response = BybitRestResponseError(
        ret_code=10001, ret_msg="Internal system error"
    )
    client = BybitFuturesExchangeClient(rest=rest, mapper=BybitExchangeMapper())

    with pytest.raises(ExchangeError, match="Failed to cancel protection order"):
        await client.ensure_stop_loss_order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("0.1"),
            stop_loss=Decimal("60000"),
            client_algo_id="bybit_stop_new",
            previous_client_algo_id="bybit_stop_old",
        )

    create_calls = [c for c in rest.calls if c[1] == "/v5/order/create"]
    cancel_calls = [c for c in rest.calls if c[1] == "/v5/order/cancel"]
    assert len(create_calls) == 1
    assert len(cancel_calls) == 1
    assert rest.calls.index(create_calls[0]) < rest.calls.index(cancel_calls[0])
