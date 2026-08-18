"""Binance USD(S)-M Futures client contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.constants import (
    BINANCE_FUTURES_TESTNET_WEBSOCKET_BASE_URL,
    BINANCE_FUTURES_WEBSOCKET_BASE_URL,
)
from botragram.enums import (
    ExchangeType,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.exchanges.base.rest import (
    JsonObject,
    JsonResponse,
    QueryParams,
    RequestHeaders,
)
from botragram.exchanges.binance.futures_client import (
    BinanceFuturesExchangeClient,
)
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.exchanges.factory import ExchangeFactory
from botragram.models import Order

_NOW = datetime(2026, 8, 7, tzinfo=UTC)


class RecordingBinanceRestClient(BinanceRestClient):
    """Return configured payloads and record Futures client requests."""

    __slots__ = ("delete_responses", "get_responses", "requests", "response")

    def __init__(self) -> None:
        """Initialize an isolated recording transport."""
        super().__init__(base_url="https://example.test")
        self.get_responses: dict[str, JsonResponse] = {}
        self.delete_responses: dict[str, JsonResponse] = {}
        self.response: JsonResponse = _order_payload()
        self.requests: list[tuple[str, str, QueryParams | None, bool]] = []

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Record a GET request and return its configured response."""
        del headers
        self.requests.append(("GET", path, params, authenticated))
        return self.get_responses.get(path, {})

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: JsonObject | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Record a POST request and return the current response."""
        del data, headers
        self.requests.append(("POST", path, params, authenticated))
        return self.response

    async def delete(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Record a DELETE request and return its configured response."""
        del headers
        self.requests.append(("DELETE", path, params, authenticated))
        return self.delete_responses.get(path, self.response)


class InMemoryProtectionClient(BinanceFuturesExchangeClient):
    """Exercise idempotent stop replacement without network access."""

    __slots__ = ("cancelled", "created", "open_protections")

    def __init__(self, *, orders: list[Order]) -> None:
        """Initialize with mutable exchange-side protection state."""
        super().__init__(
            rest=RecordingBinanceRestClient(),
            mapper=BinanceExchangeMapper(),
        )
        self.open_protections = orders
        self.created = 0
        self.cancelled: list[str] = []

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> tuple[Order, ...]:
        """Return matching in-memory protections."""
        if symbol is None:
            return tuple(self.open_protections)

        return tuple(order for order in self.open_protections if order.symbol == symbol)

    async def create_protection_orders(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        stop_loss_client_algo_id: str | None = None,
        take_profit_client_algo_id: str | None = None,
    ) -> tuple[Order, ...]:
        """Create only the requested in-memory protection legs."""
        created: list[Order] = []

        for order_type, trigger, client_algo_id in (
            (OrderType.STOP_MARKET, stop_loss, stop_loss_client_algo_id),
            (
                OrderType.TAKE_PROFIT_MARKET,
                take_profit,
                take_profit_client_algo_id,
            ),
        ):
            if trigger is None:
                continue

            self.created += 1
            order = _protection_order(
                order_id=f"new-{self.created}",
                order_type=order_type,
                stop_price=trigger,
            )
            assert client_algo_id is not None
            self.open_protections.append(order)
            created.append(order)

        return tuple(created)

    async def _cancel_algo_order(self, *, symbol: str, order_id: str) -> None:
        """Remove one matching in-memory protection."""
        self.cancelled.append(order_id)
        self.open_protections = [
            order
            for order in self.open_protections
            if not (order.symbol == symbol and order.order_id == order_id)
        ]


def _order_payload() -> JsonObject:
    """Return a complete Binance order payload."""
    return {
        "orderId": 42,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "status": "NEW",
        "origQty": "0.01",
        "executedQty": "0",
        "price": "0",
        "stopPrice": "0",
        "updateTime": 1_700_000_000_000,
        "time": 1_700_000_000_000,
    }


def _protection_order(
    *,
    order_id: str,
    order_type: OrderType,
    stop_price: Decimal,
) -> Order:
    """Return one deterministic Futures protection order."""
    return Order(
        order_id=order_id,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=order_type,
        status=OrderStatus.NEW,
        quantity=Decimal("1"),
        executed_quantity=Decimal("0"),
        price=None,
        stop_price=stop_price,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _create_client(
    rest: RecordingBinanceRestClient,
) -> BinanceFuturesExchangeClient:
    """Create a Futures client around a recording transport."""
    return BinanceFuturesExchangeClient(
        rest=rest,
        mapper=BinanceExchangeMapper(),
    )


def test_factory_builds_binance_futures_client() -> None:
    """Verify market selection constructs the dedicated Futures client."""
    exchange_client, _ = ExchangeFactory.create(
        exchange_type=ExchangeType.BINANCE,
        market_type=MarketType.FUTURES,
        rest_base_url="https://example.test",
        websocket_base_url="wss://example.test",
    )

    assert isinstance(exchange_client, BinanceFuturesExchangeClient)


def test_futures_ticker_uses_the_routed_market_websocket_endpoint() -> None:
    """Prevent silent subscriptions through Binance's retired legacy route."""
    assert BINANCE_FUTURES_WEBSOCKET_BASE_URL == ("wss://fstream.binance.com/market")
    assert BINANCE_FUTURES_TESTNET_WEBSOCKET_BASE_URL == (
        "wss://demo-fstream.binance.com/market"
    )


def test_mapper_maps_futures_collateral_account() -> None:
    """Verify Futures collateral becomes an available domain balance."""
    account = BinanceExchangeMapper().map_futures_account(
        {
            "canTrade": True,
            "assets": [
                {
                    "asset": "USDT",
                    "walletBalance": "125",
                    "availableBalance": "100",
                }
            ],
        }
    )

    assert account.can_trade
    assert not account.can_deposit
    assert account.balances[0].free == Decimal("100")
    assert account.balances[0].locked == Decimal("25")


@pytest.mark.asyncio
async def test_futures_client_lists_active_usdt_perpetual_symbols() -> None:
    """Exclude inactive, dated, and differently quoted Futures contracts."""
    rest = RecordingBinanceRestClient()
    rest.get_responses["/fapi/v1/exchangeInfo"] = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
            },
            {
                "symbol": "ETHUSDT_260925",
                "status": "TRADING",
                "quoteAsset": "USDT",
                "contractType": "CURRENT_QUARTER",
            },
            {
                "symbol": "OLDUSDT",
                "status": "SETTLING",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
            },
            {
                "symbol": "BTCUSDC",
                "status": "TRADING",
                "quoteAsset": "USDC",
                "contractType": "PERPETUAL",
            },
        ]
    }
    client = _create_client(rest)

    symbols = await client.get_trading_symbols(quote_asset="usdt")

    assert symbols == ("BTCUSDT",)
    assert rest.requests == [("GET", "/fapi/v1/exchangeInfo", None, False)]


@pytest.mark.asyncio
async def test_futures_client_creates_limit_order() -> None:
    """Verify Futures limit orders use the fapi endpoint and GTC."""
    rest = RecordingBinanceRestClient()
    client = _create_client(rest)

    await client.create_order(
        symbol="btcusdt",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.01"),
        price=Decimal("50000"),
    )

    method, path, params, authenticated = rest.requests[0]
    assert method == "POST"
    assert path == "/fapi/v1/order"
    assert params is not None
    assert params["symbol"] == "BTCUSDT"
    assert params["timeInForce"] == "GTC"
    assert authenticated


@pytest.mark.asyncio
async def test_futures_client_queries_order_by_exact_client_order_id() -> None:
    """Use Binance's Futures client-order query parameter without a POST."""
    rest = RecordingBinanceRestClient()
    rest.get_responses["/fapi/v1/order"] = {
        **_order_payload(),
        "clientOrderId": "btg-00000000000000000000000000000000",
    }
    client = _create_client(rest)

    order = await client.get_order_by_client_order_id(
        symbol="btcusdt",
        client_order_id="btg-00000000000000000000000000000000",
    )

    assert order.client_order_id == "btg-00000000000000000000000000000000"
    assert rest.requests == [
        (
            "GET",
            "/fapi/v1/order",
            {
                "symbol": "BTCUSDT",
                "origClientOrderId": "btg-00000000000000000000000000000000",
            },
            True,
        )
    ]


@pytest.mark.asyncio
async def test_futures_client_creates_reduce_only_protection_orders() -> None:
    """Verify stop-loss and take-profit exits cannot increase exposure."""
    rest = RecordingBinanceRestClient()
    client = _create_client(rest)

    orders = await client.create_protection_orders(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("0.01"),
        stop_loss=Decimal("49000"),
        take_profit=Decimal("52000"),
        stop_loss_client_algo_id="bsl-00000000000000000000000000000000",
        take_profit_client_algo_id="btp-00000000000000000000000000000000",
    )

    request_params = [request[2] for request in rest.requests]
    assert len(orders) == 2
    assert all(request[1] == "/fapi/v1/algoOrder" for request in rest.requests)
    assert all(params is not None for params in request_params)
    assert all(
        params["algoType"] == "CONDITIONAL" for params in request_params if params
    )
    assert all(params["reduceOnly"] == "true" for params in request_params if params)
    assert [params["type"] for params in request_params if params] == [
        "STOP_MARKET",
        "TAKE_PROFIT_MARKET",
    ]
    assert [params["triggerPrice"] for params in request_params if params] == [
        "49000",
        "52000",
    ]
    assert [params["clientAlgoId"] for params in request_params if params] == [
        "bsl-00000000000000000000000000000000",
        "btp-00000000000000000000000000000000",
    ]


@pytest.mark.asyncio
async def test_futures_stop_replacement_is_verified_and_idempotent() -> None:
    """Create the tighter stop first and preserve the independent TP leg."""
    old_stop = _protection_order(
        order_id="old-stop",
        order_type=OrderType.STOP_MARKET,
        stop_price=Decimal("100.5"),
    )
    take_profit = _protection_order(
        order_id="take-profit",
        order_type=OrderType.TAKE_PROFIT_MARKET,
        stop_price=Decimal("99"),
    )
    client = InMemoryProtectionClient(orders=[old_stop, take_profit])

    first = await client.ensure_stop_loss_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        stop_loss=Decimal("99.7"),
        client_algo_id="bsl-00000000000000000000000000000000",
    )
    second = await client.ensure_stop_loss_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        stop_loss=Decimal("99.7"),
        client_algo_id="bsl-00000000000000000000000000000000",
    )

    assert first.order_id == second.order_id
    assert client.created == 1
    assert client.cancelled == ["old-stop"]
    assert {order.order_id for order in client.open_protections} == {
        "new-1",
        "take-profit",
    }


@pytest.mark.asyncio
async def test_futures_client_reads_and_closes_short_position() -> None:
    """Verify a short position closes with a reduce-only buy order."""
    rest = RecordingBinanceRestClient()
    rest.get_responses["/fapi/v3/positionRisk"] = [
        {
            "symbol": "BTCUSDT",
            "positionSide": "BOTH",
            "positionAmt": "-0.02",
            "entryPrice": "50000",
            "markPrice": "49000",
            "unRealizedProfit": "20",
            "leverage": "2",
            "updateTime": 1_700_000_000_000,
        }
    ]
    client = _create_client(rest)

    positions = await client.get_positions(symbol="BTCUSDT")
    await client.close_position(symbol="BTCUSDT")

    close_params = rest.requests[-1][2]
    assert positions[0].side is PositionSide.SHORT
    assert close_params is not None
    assert close_params["side"] == "BUY"
    assert close_params["quantity"] == "0.02"
    assert close_params["reduceOnly"] == "true"
