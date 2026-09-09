"""
Botragram

Description:
    Regression tests for Bybit protection order history and closed-pnl retry.

Python:
    3.14+
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.enums import OrderStatus, OrderType
from botragram.exceptions import ExchangeOrderNotFoundError
from botragram.exchanges.base.rest import (
    JsonObject,
    JsonResponse,
    QueryParams,
    RequestHeaders,
)
from botragram.exchanges.bybit.futures_client import BybitFuturesExchangeClient
from botragram.exchanges.bybit.mapper import BybitExchangeMapper
from botragram.exchanges.bybit.rest import BybitRestClient


class _MockRestClient(BybitRestClient):
    """Controllable mock REST client."""

    def __init__(self) -> None:
        super().__init__(
            base_url="https://api.bybit.com",
            api_key="key",
            api_secret="secret",
        )
        self.history: list[tuple[str, str, QueryParams | None]] = []
        self.responses: dict[str, list[JsonResponse]] = {}

    def set_response(self, path: str, response: JsonResponse) -> None:
        self.responses.setdefault(path, []).append(response)

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        del headers, authenticated
        self.history.append(("GET", path, params))
        queue = self.responses.get(path, [])
        if queue:
            response = queue.pop(0) if len(queue) > 1 else queue[0]
        else:
            default_resp: JsonObject = {
                "retCode": 0,
                "retMsg": "OK",
                "result": {"list": []},
            }
            response = default_resp
        return self._validate_response_envelope(response)


@pytest.mark.asyncio
async def test_get_protection_order_by_client_id_falls_back_to_history() -> None:
    """When order is not in realtime (e.g. FILLED), it falls back to history."""
    rest = _MockRestClient()
    mapper = BybitExchangeMapper()
    client = BybitFuturesExchangeClient(rest=rest, mapper=mapper)

    # Realtime returns empty list (order has already filled and left realtime)
    rest.set_response(
        "/v5/order/realtime",
        {"retCode": 0, "retMsg": "OK", "result": {"list": []}},
    )

    # History returns the filled order
    rest.set_response(
        "/v5/order/history",
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "orderId": "order-123",
                        "orderLinkId": "bsl-test",
                        "symbol": "BTCUSDT",
                        "side": "Sell",
                        "orderType": "Market",
                        "stopOrderType": "StopLoss",
                        "orderStatus": "Filled",
                        "qty": "1.0",
                        "cumExecQty": "1.0",
                        "triggerPrice": "95.0",
                        "price": "95.0",
                        "createdTime": "1700000000000",
                        "updatedTime": "1700000001000",
                    }
                ]
            },
        },
    )

    order = await client.get_protection_order_by_client_id(
        symbol="BTCUSDT",
        client_id="bsl-test",
    )

    assert order.order_id == "order-123"
    assert order.client_order_id == "bsl-test"
    assert order.status is OrderStatus.FILLED
    assert order.order_type is OrderType.STOP_MARKET

    # Verified that both endpoints were queried in sequence
    paths = [item[1] for item in rest.history]
    assert paths == ["/v5/order/realtime", "/v5/order/history"]


@pytest.mark.asyncio
async def test_get_protection_order_by_client_id_not_found_raises() -> None:
    """
    When order is in neither realtime nor history,
    ExchangeOrderNotFoundError is raised.
    """
    rest = _MockRestClient()
    mapper = BybitExchangeMapper()
    client = BybitFuturesExchangeClient(rest=rest, mapper=mapper)

    rest.set_response(
        "/v5/order/realtime",
        {"retCode": 0, "retMsg": "OK", "result": {"list": []}},
    )
    rest.set_response(
        "/v5/order/history",
        {"retCode": 0, "retMsg": "OK", "result": {"list": []}},
    )

    with pytest.raises(ExchangeOrderNotFoundError):
        await client.get_protection_order_by_client_id(
            symbol="BTCUSDT",
            client_id="nonexistent-id",
        )


@pytest.mark.asyncio
async def test_get_protection_order_history_queries_order_history_endpoint() -> None:
    """get_protection_order_history queries /v5/order/history with StopOrder filter."""
    rest = _MockRestClient()
    mapper = BybitExchangeMapper()
    client = BybitFuturesExchangeClient(rest=rest, mapper=mapper)

    rest.set_response(
        "/v5/order/history",
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "orderId": "order-tp-1",
                        "orderLinkId": "btp-test",
                        "symbol": "BTCUSDT",
                        "side": "Sell",
                        "orderType": "Market",
                        "stopOrderType": "TakeProfit",
                        "orderStatus": "Filled",
                        "qty": "0.5",
                        "cumExecQty": "0.5",
                        "triggerPrice": "105.0",
                        "createdTime": "1700000000000",
                        "updatedTime": "1700000002000",
                    }
                ]
            },
        },
    )

    start_time = datetime(2026, 8, 20, tzinfo=UTC)
    orders = await client.get_protection_order_history(
        symbol="BTCUSDT",
        start_time=start_time,
    )

    assert len(orders) == 1
    assert orders[0].order_id == "order-tp-1"
    assert orders[0].order_type is OrderType.TAKE_PROFIT_MARKET
    assert orders[0].status is OrderStatus.FILLED

    assert len(rest.history) == 1
    assert rest.history[0][1] == "/v5/order/history"
    params = rest.history[0][2]
    assert params is not None
    assert params.get("orderFilter") == "StopOrder"
    assert params.get("symbol") == "BTCUSDT"


@pytest.mark.asyncio
async def test_get_trades_for_order_retries_closed_pnl() -> None:
    """get_trades_for_order retries closed-pnl lookup if initially empty."""
    rest = _MockRestClient()
    mapper = BybitExchangeMapper()
    client = BybitFuturesExchangeClient(rest=rest, mapper=mapper)

    # Execution list returns a fill without realized PnL
    rest.set_response(
        "/v5/execution/list",
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "execId": "exec-1",
                        "orderId": "exit-123",
                        "symbol": "BTCUSDT",
                        "side": "Sell",
                        "execPrice": "105.0",
                        "execQty": "1.0",
                        "execFee": "0.01",
                        "feeCurrency": "USDT",
                        "execTime": "1700000000000",
                        "closedPnl": "",  # Empty on initial execution query
                    }
                ]
            },
        },
    )

    # Closed PnL returns empty on attempt 1, and populated on attempt 2
    rest.responses["/v5/position/closed-pnl"] = [
        {"retCode": 0, "retMsg": "OK", "result": {"list": []}},
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "orderId": "exit-123",
                        "symbol": "BTCUSDT",
                        "closedPnl": "5.0",
                    }
                ]
            },
        },
    ]

    trades = await client.get_trades_for_order(
        symbol="BTCUSDT",
        order_id="exit-123",
    )

    assert len(trades) == 1
    assert trades[0].order_id == "exit-123"
    assert trades[0].realized_pnl == Decimal("5.0")


@pytest.mark.asyncio
async def test_get_trades_for_order_un_deducts_fees_from_closed_pnl() -> None:
    """Bybit closedPnl is net of fees; get_trades_for_order reconstructs gross PnL."""
    rest = _MockRestClient()
    mapper = BybitExchangeMapper()
    client = BybitFuturesExchangeClient(rest=rest, mapper=mapper)

    rest.set_response(
        "/v5/execution/list",
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "execId": "exec-1",
                        "orderId": "exit-123",
                        "symbol": "BTCUSDT",
                        "side": "Sell",
                        "execPrice": "105.0",
                        "execQty": "1.0",
                        "execFee": "0.01",
                        "feeCurrency": "USDT",
                        "execTime": "1700000000000",
                        "closedPnl": "",
                    }
                ]
            },
        },
    )

    rest.set_response(
        "/v5/position/closed-pnl",
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "orderId": "exit-123",
                        "symbol": "BTCUSDT",
                        "closedPnl": "0.07246458",
                        "openFee": "0.0051183",
                        "closeFee": "0.00532622",
                    }
                ]
            },
        },
    )

    trades = await client.get_trades_for_order(
        symbol="BTCUSDT",
        order_id="exit-123",
    )

    assert len(trades) == 1
    assert trades[0].order_id == "exit-123"
    # Gross PnL = 0.07246458 + 0.0051183 + 0.00532622 = 0.08290910
    assert trades[0].realized_pnl == Decimal("0.08290910")
