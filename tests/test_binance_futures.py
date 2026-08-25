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
from botragram.exceptions import (
    ExchangeOrderImmediateTriggerRejectedError,
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderPriceBandRejectedError,
    ExchangeOrderRejectedError,
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
from botragram.exchanges.binance.rest import (
    BinanceRestClient,
    BinanceRestResponseError,
)
from botragram.exchanges.factory import ExchangeFactory
from botragram.models import MarketUniverseEntry, Order

_NOW = datetime(2026, 8, 7, tzinfo=UTC)
_EXCHANGE_INFO_ENDPOINT = "/fapi/v1/exchangeInfo"
_BULK_TICKER_ENDPOINT = "/fapi/v1/ticker/24hr"
_TRADES_ENDPOINT = "/fapi/v1/userTrades"


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


@pytest.mark.asyncio
async def test_get_trades_for_order_uses_exact_authenticated_order_identity() -> None:
    """Never depend on a latest-account-fill window for lifecycle enrichment."""
    rest = RecordingBinanceRestClient()
    rest.get_responses[_TRADES_ENDPOINT] = [
        {
            "id": 7,
            "orderId": 42,
            "symbol": "BTCUSDT",
            "side": "SELL",
            "price": "101",
            "qty": "1",
            "quoteQty": "101",
            "commission": "0.1",
            "commissionAsset": "USDT",
            "realizedPnl": "1",
            "time": 1_700_000_000_000,
        }
    ]
    client = BinanceFuturesExchangeClient(
        rest=rest,
        mapper=BinanceExchangeMapper(),
    )

    trades = await client.get_trades_for_order(
        symbol="btcusdt",
        order_id="42",
    )

    assert len(trades) == 1
    assert trades[0].order_id == "42"
    assert rest.requests == [
        (
            "GET",
            _TRADES_ENDPOINT,
            {"symbol": "BTCUSDT", "orderId": "42", "limit": 1_000},
            True,
        )
    ]


class PriceBandRejectingRestClient(RecordingBinanceRestClient):
    """Reject every order POST with Binance PERCENT_PRICE code -4131."""

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: JsonObject | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Raise one explicit structured price-band rejection."""
        del path, params, data, headers, authenticated
        raise BinanceRestResponseError(
            status=400,
            payload={
                "code": -4131,
                "msg": "The counterparty's best price does not meet the "
                "PERCENT_PRICE filter limit.",
            },
            message="configured PERCENT_PRICE rejection",
        )


class ProtectionRejectingRestClient(RecordingBinanceRestClient):
    """Raise one configurable explicit Binance protection rejection."""

    __slots__ = ("error_code",)

    def __init__(self, *, error_code: int) -> None:
        """Initialize one deterministic structured rejection."""
        super().__init__()
        self.error_code = error_code

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: JsonObject | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Reject one conditional protection POST without transport ambiguity."""
        del path, params, data, headers, authenticated
        raise BinanceRestResponseError(
            status=400,
            payload={"code": self.error_code, "msg": "configured rejection"},
            message="configured protection rejection",
        )


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
            assert client_algo_id is not None
            order = _protection_order(
                order_id=f"new-{self.created}",
                order_type=order_type,
                stop_price=trigger,
                client_id=client_algo_id,
            )
            self.open_protections.append(order)
            created.append(order)

        return tuple(created)

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        """Return one exact in-memory conditional identity."""
        for order in self.open_protections:
            if order.symbol == symbol and order.client_order_id == client_id:
                return order
        raise ExchangeOrderNotFoundError("configured protection not found")

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> None:
        """Cancel one exact in-memory conditional identity."""
        for order in tuple(self.open_protections):
            if order.symbol == symbol and order.client_order_id == client_id:
                self.cancelled.append(order.order_id)
                self.open_protections.remove(order)
                return
        raise ExchangeOrderNotFoundError("configured protection not found")

    async def _cancel_algo_order(self, *, symbol: str, order_id: str) -> None:
        """Remove one matching in-memory protection."""
        self.cancelled.append(order_id)
        self.open_protections = [
            order
            for order in self.open_protections
            if not (order.symbol == symbol and order.order_id == order_id)
        ]


class AmbiguousInMemoryProtectionClient(InMemoryProtectionClient):
    """Model a timed-out replacement POST that is later proven by client ID."""

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
        """Create once remotely but expose only an ambiguous local outcome."""
        await super().create_protection_orders(
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            stop_loss_client_algo_id=stop_loss_client_algo_id,
            take_profit_client_algo_id=take_profit_client_algo_id,
        )
        raise ExchangeOrderOutcomeUnknownError("configured ambiguous POST outcome")

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        """Prove only an actually-created replacement through exact identity."""
        return await super().get_protection_order_by_client_id(
            symbol=symbol,
            client_id=client_id,
        )


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
    client_id: str | None = None,
) -> Order:
    """Return one deterministic Futures protection order."""
    return Order(
        order_id=order_id,
        client_order_id=client_id,
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


def _market_symbol(
    symbol: str,
    *,
    status: str = "TRADING",
    quote_asset: str = "USDT",
    contract_type: str = "PERPETUAL",
) -> JsonObject:
    """Return one Binance Futures exchangeInfo symbol row."""
    return {
        "symbol": symbol,
        "status": status,
        "quoteAsset": quote_asset,
        "contractType": contract_type,
    }


def _configure_market_universe(
    rest: RecordingBinanceRestClient,
    *,
    symbols: list[JsonObject],
    tickers: JsonResponse,
) -> None:
    """Configure authoritative symbols and one bulk ticker snapshot."""
    rest.get_responses[_EXCHANGE_INFO_ENDPOINT] = {"symbols": symbols}
    rest.get_responses[_BULK_TICKER_ENDPOINT] = tickers


@pytest.mark.asyncio
async def test_futures_client_classifies_percent_price_order_rejection() -> None:
    """Expose Binance -4131 as a typed price-band rejection."""
    client = _create_client(PriceBandRejectingRestClient())

    with pytest.raises(ExchangeOrderPriceBandRejectedError):
        await client.create_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.01"),
        )


@pytest.mark.asyncio
async def test_futures_protection_post_classifies_immediate_trigger_rejection() -> None:
    """Map only Binance -2021 to the typed conditional-order rejection."""
    client = _create_client(ProtectionRejectingRestClient(error_code=-2021))

    with pytest.raises(ExchangeOrderImmediateTriggerRejectedError) as captured:
        await client.create_protection_orders(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("0.01"),
            stop_loss=Decimal("64000"),
            stop_loss_client_algo_id="bsl-00000000000000000000000000000000",
        )

    assert isinstance(captured.value, ExchangeOrderRejectedError)


@pytest.mark.asyncio
async def test_futures_protection_post_keeps_other_explicit_rejections_generic() -> (
    None
):
    """Do not infer immediate triggering from any other Binance rejection."""
    client = _create_client(ProtectionRejectingRestClient(error_code=-2010))

    with pytest.raises(ExchangeOrderRejectedError) as captured:
        await client.create_protection_orders(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("0.01"),
            stop_loss=Decimal("64000"),
            stop_loss_client_algo_id="bsl-00000000000000000000000000000000",
        )

    assert not isinstance(captured.value, ExchangeOrderImmediateTriggerRejectedError)


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
async def test_futures_market_universe_uses_bulk_volume_ranking() -> None:
    """Call both public endpoints and rank typed facts deterministically."""
    rest = RecordingBinanceRestClient()
    _configure_market_universe(
        rest,
        symbols=[
            _market_symbol("BTCUSDT"),
            _market_symbol("ETHUSDT"),
            _market_symbol("SOLUSDT"),
        ],
        tickers=[
            {"symbol": "BTCUSDT", "quoteVolume": "100"},
            {"symbol": "SOLUSDT", "quoteVolume": "500"},
            {"symbol": "ETHUSDT", "quoteVolume": "500"},
        ],
    )
    client = _create_client(rest)

    universe = await client.get_market_universe(quote_asset="usdt")

    assert universe == (
        MarketUniverseEntry(symbol="ETHUSDT", quote_volume=Decimal("500")),
        MarketUniverseEntry(symbol="SOLUSDT", quote_volume=Decimal("500")),
        MarketUniverseEntry(symbol="BTCUSDT", quote_volume=Decimal("100")),
    )
    assert all(isinstance(entry, MarketUniverseEntry) for entry in universe)
    assert rest.requests == [
        ("GET", _EXCHANGE_INFO_ENDPOINT, None, False),
        ("GET", _BULK_TICKER_ENDPOINT, None, False),
    ]


@pytest.mark.asyncio
async def test_futures_market_universe_cross_filters_eligible_symbols() -> None:
    """Ignore inactive, wrong-quote, dated, and unknown ticker rows."""
    rest = RecordingBinanceRestClient()
    _configure_market_universe(
        rest,
        symbols=[
            _market_symbol("BTCUSDT"),
            _market_symbol("OLDUSDT", status="SETTLING"),
            _market_symbol("BTCUSDC", quote_asset="USDC"),
            _market_symbol("ETHUSDT_260925", contract_type="CURRENT_QUARTER"),
        ],
        tickers=[
            {"symbol": "BTCUSDT", "quoteVolume": "100"},
            {"symbol": "OLDUSDT", "quoteVolume": "not-a-decimal"},
            {"symbol": "BTCUSDC", "quoteVolume": "not-a-decimal"},
            {"symbol": "ETHUSDT_260925", "quoteVolume": "not-a-decimal"},
            {"symbol": "UNKNOWNUSDT", "quoteVolume": "not-a-decimal"},
        ],
    )

    universe = await _create_client(rest).get_market_universe(quote_asset="USDT")

    assert universe == (
        MarketUniverseEntry(symbol="BTCUSDT", quote_volume=Decimal("100")),
    )


@pytest.mark.asyncio
async def test_futures_market_universe_ignores_missing_active_ticker() -> None:
    """Accept snapshot skew when one authoritative active ticker is absent."""
    rest = RecordingBinanceRestClient()
    _configure_market_universe(
        rest,
        symbols=[_market_symbol("BTCUSDT"), _market_symbol("ETHUSDT")],
        tickers=[{"symbol": "BTCUSDT", "quoteVolume": "100"}],
    )

    universe = await _create_client(rest).get_market_universe(quote_asset="USDT")

    assert tuple(entry.symbol for entry in universe) == ("BTCUSDT",)


@pytest.mark.asyncio
async def test_futures_market_universe_accepts_and_ranks_zero_volume() -> None:
    """Retain zero volume and rank it below positive quote volume."""
    rest = RecordingBinanceRestClient()
    _configure_market_universe(
        rest,
        symbols=[_market_symbol("BTCUSDT"), _market_symbol("ETHUSDT")],
        tickers=[
            {"symbol": "BTCUSDT", "quoteVolume": "0"},
            {"symbol": "ETHUSDT", "quoteVolume": "1"},
        ],
    )

    universe = await _create_client(rest).get_market_universe(quote_asset="USDT")

    assert tuple((entry.symbol, entry.quote_volume) for entry in universe) == (
        ("ETHUSDT", Decimal("1")),
        ("BTCUSDT", Decimal("0")),
    )


@pytest.mark.asyncio
async def test_futures_market_universe_rejects_duplicate_eligible_ticker() -> None:
    """Fail when two bulk rows normalize to the same eligible symbol."""
    rest = RecordingBinanceRestClient()
    _configure_market_universe(
        rest,
        symbols=[_market_symbol("BTCUSDT")],
        tickers=[
            {"symbol": "BTCUSDT", "quoteVolume": "100"},
            {"symbol": " btcusdt ", "quoteVolume": "90"},
        ],
    )

    with pytest.raises(ValueError, match="duplicate eligible symbol"):
        await _create_client(rest).get_market_universe(quote_asset="USDT")


@pytest.mark.parametrize(
    "ticker_payload",
    (
        {"symbol": "BTCUSDT"},
        {"symbol": "BTCUSDT", "quoteVolume": "not-a-decimal"},
        {"symbol": "BTCUSDT", "quoteVolume": "NaN"},
        {"symbol": "BTCUSDT", "quoteVolume": "Infinity"},
        {"symbol": "BTCUSDT", "quoteVolume": "-1"},
    ),
)
@pytest.mark.asyncio
async def test_futures_market_universe_rejects_invalid_eligible_volume(
    ticker_payload: JsonObject,
) -> None:
    """Fail rather than manufacture a usable eligible quote volume."""
    rest = RecordingBinanceRestClient()
    _configure_market_universe(
        rest,
        symbols=[_market_symbol("BTCUSDT")],
        tickers=[ticker_payload],
    )

    with pytest.raises(ValueError):
        await _create_client(rest).get_market_universe(quote_asset="USDT")


@pytest.mark.asyncio
async def test_futures_market_universe_rejects_malformed_top_level_ticker() -> None:
    """Require the bulk 24-hour ticker payload to be an array."""
    rest = RecordingBinanceRestClient()
    _configure_market_universe(
        rest,
        symbols=[_market_symbol("BTCUSDT")],
        tickers={},
    )

    with pytest.raises(ValueError):
        await _create_client(rest).get_market_universe(quote_asset="USDT")


@pytest.mark.parametrize(
    "ticker_rows",
    (
        [{"quoteVolume": "100"}],
        ["not-a-mapping"],
    ),
)
@pytest.mark.asyncio
async def test_futures_market_universe_rejects_unprovable_ticker_identity(
    ticker_rows: list[object],
) -> None:
    """Fail when a bulk row cannot prove which symbol it represents."""
    rest = RecordingBinanceRestClient()
    _configure_market_universe(
        rest,
        symbols=[_market_symbol("BTCUSDT")],
        tickers=ticker_rows,
    )

    with pytest.raises(ValueError):
        await _create_client(rest).get_market_universe(quote_asset="USDT")


@pytest.mark.asyncio
async def test_futures_market_universe_rejects_empty_usable_ranking() -> None:
    """Fail when the bulk snapshot contains no usable eligible symbol."""
    rest = RecordingBinanceRestClient()
    _configure_market_universe(
        rest,
        symbols=[_market_symbol("BTCUSDT")],
        tickers=[{"symbol": "UNKNOWNUSDT", "quoteVolume": "not-a-decimal"}],
    )

    with pytest.raises(ValueError, match="no usable ranked symbols"):
        await _create_client(rest).get_market_universe(quote_asset="USDT")


@pytest.mark.asyncio
async def test_futures_client_reads_executable_quote_from_book_ticker() -> None:
    """Use the Futures book ticker because 24-hour payloads lack bid and ask."""
    rest = RecordingBinanceRestClient()
    rest.get_responses["/fapi/v1/ticker/bookTicker"] = {
        "symbol": "BTCUSDT",
        "bidPrice": "99.5",
        "askPrice": "100.5",
        "time": 1_700_000_000_000,
    }
    client = _create_client(rest)

    quote = await client.get_executable_quote(symbol=" btcusdt ")

    assert quote.symbol == "BTCUSDT"
    assert quote.bid_price == Decimal("99.5")
    assert quote.ask_price == Decimal("100.5")
    assert quote.timestamp == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert rest.requests == [
        (
            "GET",
            "/fapi/v1/ticker/bookTicker",
            {"symbol": "BTCUSDT"},
            False,
        )
    ]


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
async def test_futures_ambiguous_stop_replacement_reconciles_before_old_cancel() -> (
    None
):
    """GET-reconcile one ambiguous replacement and only then remove its predecessor."""
    old_stop = _protection_order(
        order_id="old-stop",
        order_type=OrderType.STOP_MARKET,
        stop_price=Decimal("100.5"),
    )
    client = AmbiguousInMemoryProtectionClient(orders=[old_stop])

    replacement = await client.ensure_stop_loss_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        stop_loss=Decimal("99.7"),
        client_algo_id="bsl-00000000000000000000000000000000",
    )

    assert replacement.client_order_id == "bsl-00000000000000000000000000000000"
    assert client.created == 1
    assert client.cancelled == ["old-stop"]


@pytest.mark.asyncio
async def test_futures_immediate_rejection_keeps_predecessor() -> None:
    """Never retire the current STOP when pending POST is explicitly rejected."""

    class ImmediateTriggerRejectedProtectionClient(InMemoryProtectionClient):
        def __init__(self, *, orders: list[Order]) -> None:
            super().__init__(orders=orders)
            self.predecessor_retirements = 0

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
            del (
                symbol,
                side,
                quantity,
                stop_loss,
                take_profit,
                stop_loss_client_algo_id,
                take_profit_client_algo_id,
            )
            raise ExchangeOrderImmediateTriggerRejectedError(
                "configured immediate trigger rejection"
            )

        async def _retire_stop_loss_predecessor(
            self,
            *,
            symbol: str,
            side: OrderSide,
            quantity: Decimal,
            client_algo_id: str,
        ) -> None:
            del symbol, side, quantity, client_algo_id
            self.predecessor_retirements += 1

    predecessor_id = "bsl-11111111111111111111111111111111"
    client = ImmediateTriggerRejectedProtectionClient(
        orders=[
            _protection_order(
                order_id="old-stop",
                order_type=OrderType.STOP_MARKET,
                stop_price=Decimal("100.5"),
                client_id=predecessor_id,
            )
        ]
    )

    with pytest.raises(ExchangeOrderImmediateTriggerRejectedError):
        await client.ensure_stop_loss_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            stop_loss=Decimal("99.7"),
            client_algo_id="bsl-22222222222222222222222222222222",
            previous_client_algo_id=predecessor_id,
        )

    assert client.predecessor_retirements == 0
    assert client.cancelled == []
    assert tuple(order.client_order_id for order in client.open_protections) == (
        predecessor_id,
    )


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
    await client.close_position(
        symbol="BTCUSDT",
        client_order_id="bex-0123456789abcdef0123456789abcdef",
    )

    close_params = rest.requests[-1][2]
    assert positions[0].side is PositionSide.SHORT
    assert close_params is not None
    assert close_params["side"] == "BUY"
    assert close_params["quantity"] == "0.02"
    assert close_params["reduceOnly"] == "true"
    assert close_params["newClientOrderId"] == "bex-0123456789abcdef0123456789abcdef"


def test_mapper_normalizes_finished_algo_status_to_filled() -> None:
    """Normalize Binance's terminal conditional status at the vendor boundary."""
    order = BinanceExchangeMapper().map_algo_order(
        {
            "algoId": 77,
            "clientAlgoId": "bsl-00000000000000000000000000000000",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "orderType": "STOP_MARKET",
            "algoStatus": "FINISHED",
            "quantity": "1",
            "actualQty": "1",
            "triggerPrice": "50000",
            "createTime": 1_700_000_000_000,
            "updateTime": 1_700_000_001_000,
        }
    )

    assert order.status is OrderStatus.FILLED
    assert order.executed_quantity == Decimal("1")
    assert order.client_order_id == "bsl-00000000000000000000000000000000"


def test_mapper_preserves_actual_execution_id_separately_from_algo_id() -> None:
    """Link exact fills without changing the identity used for algo operations."""
    order = BinanceExchangeMapper().map_algo_order(
        {
            "algoId": 77,
            "actualOrderId": "42001",
            "clientAlgoId": "btp-00000000000000000000000000000000",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "FINISHED",
            "quantity": "1",
            "actualQty": "1",
            "triggerPrice": "51000",
            "createTime": 1_700_000_000_000,
            "updateTime": 1_700_000_001_000,
        }
    )

    assert order.order_id == "77"
    assert order.execution_order_id == "42001"
    assert order.status is OrderStatus.FILLED


def test_mapper_normalizes_triggered_algo_status_as_in_progress() -> None:
    """Never represent an already-fired conditional leg as active protection."""
    order = BinanceExchangeMapper().map_algo_order(
        {
            "algoId": 78,
            "clientAlgoId": "bsl-00000000000000000000000000000001",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "orderType": "STOP_MARKET",
            "algoStatus": "TRIGGERED",
            "quantity": "1",
            "actualQuantity": "0",
            "triggerPrice": "50000",
            "createTime": 1_700_000_000_000,
            "updateTime": 1_700_000_001_000,
        }
    )

    assert order.status is OrderStatus.PARTIALLY_FILLED


def test_mapper_preserves_triggering_algo_status_as_transitional() -> None:
    """Reject neither a real in-flight trigger nor relabel it as active."""
    order = BinanceExchangeMapper().map_algo_order(
        {
            "algoId": 80,
            "clientAlgoId": "btp-00000000000000000000000000000003",
            "symbol": "ONUSDT",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "TRIGGERING",
            "quantity": "500",
            "actualQty": "0",
            "triggerPrice": "0.2516600",
            "createTime": 1_700_000_000_000,
            "updateTime": 1_700_000_001_000,
        }
    )

    assert order.status is OrderStatus.TRIGGERING


@pytest.mark.asyncio
async def test_futures_client_waits_for_transitional_exact_protection_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve a real transient algo state through bounded GET-only reads."""

    class TriggeringThenNewRestClient(RecordingBinanceRestClient):
        def __init__(self) -> None:
            super().__init__()
            self.algo_responses: list[JsonResponse] = [
                {
                    "algoId": 80,
                    "clientAlgoId": "btp-00000000000000000000000000000003",
                    "symbol": "ONUSDT",
                    "side": "SELL",
                    "orderType": "TAKE_PROFIT_MARKET",
                    "algoStatus": "TRIGGERING",
                    "quantity": "500",
                    "actualQty": "0",
                    "triggerPrice": "0.2516600",
                    "createTime": 1_700_000_000_000,
                    "updateTime": 1_700_000_001_000,
                },
                {
                    "algoId": 80,
                    "clientAlgoId": "btp-00000000000000000000000000000003",
                    "symbol": "ONUSDT",
                    "side": "SELL",
                    "orderType": "TAKE_PROFIT_MARKET",
                    "algoStatus": "TRIGGERING",
                    "quantity": "500",
                    "actualQty": "0",
                    "triggerPrice": "0.2516600",
                    "createTime": 1_700_000_000_000,
                    "updateTime": 1_700_000_001_000,
                },
                {
                    "algoId": 80,
                    "clientAlgoId": "btp-00000000000000000000000000000003",
                    "symbol": "ONUSDT",
                    "side": "SELL",
                    "orderType": "TAKE_PROFIT_MARKET",
                    "algoStatus": "NEW",
                    "quantity": "500",
                    "actualQty": "0",
                    "triggerPrice": "0.2516600",
                    "createTime": 1_700_000_000_000,
                    "updateTime": 1_700_000_001_000,
                },
            ]

        async def get(
            self,
            path: str,
            *,
            params: QueryParams | None = None,
            headers: RequestHeaders | None = None,
            authenticated: bool = False,
        ) -> JsonResponse:
            if path != "/fapi/v1/algoOrder":
                return await super().get(
                    path,
                    params=params,
                    headers=headers,
                    authenticated=authenticated,
                )

            del headers
            self.requests.append(("GET", path, params, authenticated))
            return self.algo_responses.pop(0)

    async def no_delay(_: float) -> None:
        """Keep the bounded transition test fast."""

    monkeypatch.setattr(
        "botragram.exchanges.binance.futures_client.asyncio.sleep",
        no_delay,
    )
    rest = TriggeringThenNewRestClient()
    order = await _create_client(rest).get_protection_order_by_client_id(
        symbol="ONUSDT",
        client_id="btp-00000000000000000000000000000003",
    )

    assert order.status is OrderStatus.NEW
    assert [request[0] for request in rest.requests] == ["GET", "GET", "GET"]
    assert all(request[1] == "/fapi/v1/algoOrder" for request in rest.requests)


def test_mapper_normalizes_failed_algo_status_to_rejected() -> None:
    """Normalize Binance's terminal failed algo state without a vendor leak."""
    order = BinanceExchangeMapper().map_algo_order(
        {
            "algoId": 79,
            "clientAlgoId": "bsl-00000000000000000000000000000002",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "orderType": "STOP_MARKET",
            "algoStatus": "FAILED",
            "quantity": "1",
            "actualQty": "0",
            "triggerPrice": "50000",
            "createTime": 1_700_000_000_000,
            "updateTime": 1_700_000_001_000,
        }
    )

    assert order.status is OrderStatus.REJECTED
    assert order.executed_quantity == Decimal("0")


@pytest.mark.asyncio
async def test_futures_client_cancels_protection_by_exact_client_identity() -> None:
    """Use one non-retried algo DELETE keyed by the durable client identity."""
    rest = RecordingBinanceRestClient()
    client = _create_client(rest)

    await client.cancel_protection_order(
        symbol="btcusdt",
        client_id="btp-00000000000000000000000000000000",
    )

    assert rest.requests == [
        (
            "DELETE",
            "/fapi/v1/algoOrder",
            {
                "clientAlgoId": "btp-00000000000000000000000000000000",
            },
            True,
        )
    ]


@pytest.mark.asyncio
async def test_futures_stop_replacement_retires_exact_predecessor() -> None:
    """Retire the predecessor identity only after exact replacement proof."""
    predecessor_id = "bsl-11111111111111111111111111111111"
    replacement_id = "bsl-22222222222222222222222222222222"
    old_stop = _protection_order(
        order_id="old-stop",
        order_type=OrderType.STOP_MARKET,
        stop_price=Decimal("100.5"),
        client_id=predecessor_id,
    )
    client = InMemoryProtectionClient(orders=[old_stop])

    replacement = await client.ensure_stop_loss_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        stop_loss=Decimal("99.7"),
        client_algo_id=replacement_id,
        previous_client_algo_id=predecessor_id,
    )

    assert replacement.client_order_id == replacement_id
    assert client.cancelled == ["old-stop"]
    assert tuple(order.client_order_id for order in client.open_protections) == (
        replacement_id,
    )
