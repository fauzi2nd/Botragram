"""
Botragram

Description:
    Bybit exchange integration test suite covering REST transport, mapper,
    clients, stream, and factory wiring.

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
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    ExchangeType,
    Interval,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.base.mapper import ExchangePayload
from botragram.exchanges.base.rest import JsonResponse, QueryParams, RequestHeaders
from botragram.exchanges.bybit.client import BybitExchangeClient
from botragram.exchanges.bybit.futures_client import BybitFuturesExchangeClient
from botragram.exchanges.bybit.mapper import BybitExchangeMapper
from botragram.exchanges.bybit.rest import (
    BybitRestClient,
    BybitRestResponseError,
)
from botragram.exchanges.bybit.stream import BybitStreamClient
from botragram.exchanges.factory import ExchangeFactory
from botragram.models import Candle, MarketUniverseEntry, Ticker


# =============================================================================
# Mock Transports
# =============================================================================
class MockBybitRestClient(BybitRestClient):
    """Mock Bybit REST client providing controllable responses."""

    __slots__ = (
        "canned_response",
        "canned_responses",
        "history",
        "last_data",
        "last_method",
        "last_params",
        "last_path",
        "post_exception",
    )

    def __init__(self) -> None:
        super().__init__(
            base_url="https://api-testnet.bybit.com",
            api_key="mock-api-key",
            api_secret="mock-api-secret",
        )
        self.history: list[tuple[str, str]] = []
        self.last_method = ""
        self.last_path = ""
        self.last_params: QueryParams | None = None
        self.last_data: dict[str, object] | None = None
        self.post_exception: Exception | None = None
        self.canned_response: JsonResponse = {
            "retCode": 0,
            "retMsg": "OK",
            "result": {},
        }
        self.canned_responses: list[JsonResponse] = []

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        del headers, authenticated
        self.history.append(("GET", path))
        self.last_method = "GET"
        self.last_path = path
        self.last_params = params
        if self.canned_responses:
            response = self.canned_responses.pop(0)
        else:
            response = self.canned_response
        return self._validate_response_envelope(response)

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: dict[str, object] | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        del headers, authenticated
        self.history.append(("POST", path))
        self.last_method = "POST"
        self.last_path = path
        self.last_params = params
        self.last_data = data
        if self.post_exception is not None:
            raise self.post_exception
        return self._validate_response_envelope(self.canned_response)

    def test_prepare_headers(self, *, payload_str: str) -> dict[str, str]:
        """Expose protected header preparation for unit tests."""
        return self._prepare_headers(authenticated=True, payload_str=payload_str)

    @staticmethod
    def test_validate_envelope(payload: JsonResponse) -> JsonResponse:
        """Expose protected response envelope validation for unit tests."""
        return MockBybitRestClient._validate_response_envelope(payload)


class MockBybitStreamClient(BybitStreamClient):
    """Test subclass exposing protected stream methods for unit tests."""

    __test__ = False

    def attach_topic_queue(self, topic: str, queue: asyncio.Queue[object]) -> None:
        """Attach an in-memory queue to a topic."""
        if topic not in self._queues:
            self._queues[topic] = set()
        self._queues[topic].add(queue)

    def inject_raw_message(self, raw_data: str) -> None:
        """Inject a raw WebSocket text message for testing."""
        self._handle_message(raw_data)


# =============================================================================
# Factory Wiring Tests
# =============================================================================
def test_exchange_factory_creates_bybit_components() -> None:
    """ExchangeFactory must create proper Bybit clients for SPOT and FUTURES."""
    rest_url = "https://api.bybit.com"
    ws_url = "wss://stream.bybit.com/v5/public/linear"

    rest = ExchangeFactory.create_rest_client(
        exchange_type=ExchangeType.BYBIT,
        base_url=rest_url,
        api_key="test-key",
        api_secret="test-secret",
    )
    assert isinstance(rest, BybitRestClient)
    assert rest.has_credentials

    # Futures client
    futures_client = ExchangeFactory.create_exchange_client(
        exchange_type=ExchangeType.BYBIT,
        rest_client=rest,
        market_type=MarketType.FUTURES,
    )
    assert isinstance(futures_client, BybitFuturesExchangeClient)

    # Spot client
    spot_client = ExchangeFactory.create_exchange_client(
        exchange_type=ExchangeType.BYBIT,
        rest_client=rest,
        market_type=MarketType.SPOT,
    )
    assert isinstance(spot_client, BybitExchangeClient)
    assert not isinstance(spot_client, BybitFuturesExchangeClient)

    # Stream client
    stream = ExchangeFactory.create_stream_client(
        exchange_type=ExchangeType.BYBIT,
        base_url=ws_url,
    )
    assert isinstance(stream, BybitStreamClient)

    # Full create bundle
    client, stream_bundle = ExchangeFactory.create(
        exchange_type=ExchangeType.BYBIT,
        rest_base_url=rest_url,
        websocket_base_url=ws_url,
        api_key="test-key",
        api_secret="test-secret",
        market_type=MarketType.FUTURES,
    )
    assert isinstance(client, BybitFuturesExchangeClient)
    assert isinstance(stream_bundle, BybitStreamClient)


def test_settings_manager_loads_bybit_settings(
    tmp_path: Path,
) -> None:
    """SettingsManager loads Bybit exchange settings and market type."""
    from botragram.app.environment_provider import EnvironmentProvider
    from botragram.app.settings_manager import SettingsManager

    env_file = tmp_path / ".env"
    env_file.write_text(
        "ACTIVE_EXCHANGE=BYBIT\n"
        "BYBIT_API_KEY=bybit-key\n"
        "BYBIT_API_SECRET=bybit-secret\n"
        "BYBIT_MARKET_TYPE=FUTURES\n"
        "BYBIT_TESTNET=true\n",
        encoding="utf-8",
    )

    provider = EnvironmentProvider(env_path=str(env_file))
    manager = SettingsManager(environment_provider=provider)
    settings = manager.load_exchange_settings()
    assert settings.exchange is ExchangeType.BYBIT
    assert settings.market_type is MarketType.FUTURES
    assert settings.api_key == "bybit-key"
    assert settings.api_secret == "bybit-secret"
    assert settings.testnet is True


# =============================================================================
# REST Transport Tests
# =============================================================================
def test_bybit_rest_signature_and_headers() -> None:
    """BybitRestClient signs correctly with HMAC-SHA256 and injects V5 headers."""
    client = MockBybitRestClient()

    headers = client.test_prepare_headers(
        payload_str='{"category":"linear"}',
    )
    assert headers["X-BAPI-API-KEY"] == "mock-api-key"
    assert headers["X-BAPI-SIGN-TYPE"] == "2"
    assert headers["X-BAPI-RECV-WINDOW"] == "5000"
    assert "X-BAPI-TIMESTAMP" in headers
    assert "X-BAPI-SIGN" in headers
    assert len(headers["X-BAPI-SIGN"]) == 64  # SHA256 hex


def test_bybit_rest_response_envelope_error() -> None:
    """BybitRestClient raises BybitRestResponseError when retCode != 0."""
    error_payload: JsonResponse = {
        "retCode": 10001,
        "retMsg": "params error: category not valid",
        "result": {},
    }
    with pytest.raises(BybitRestResponseError) as exc_info:
        MockBybitRestClient.test_validate_envelope(error_payload)

    assert exc_info.value.ret_code == 10001
    assert "category not valid" in exc_info.value.ret_msg


# =============================================================================
# Mapper Tests
# =============================================================================
def test_bybit_mapper_account() -> None:
    """Map Bybit Unified wallet balance payload into Account model."""
    mapper = BybitExchangeMapper()
    raw_payload: ExchangePayload = {
        "list": [
            {
                "accountType": "UNIFIED",
                "coin": [
                    {
                        "coin": "USDT",
                        "walletBalance": "1000.50",
                        "availableToWithdraw": "800.25",
                    },
                    {
                        "coin": "BTC",
                        "walletBalance": "0.5",
                        "availableBalance": "0.5",
                    },
                ],
            }
        ]
    }
    account = mapper.map_account(raw_payload)
    assert account.can_trade is True
    assert len(account.balances) == 2

    usdt = next(b for b in account.balances if b.asset == "USDT")
    assert usdt.free == Decimal("800.25")
    assert usdt.locked == Decimal("200.25")

    btc = next(b for b in account.balances if b.asset == "BTC")
    assert btc.free == Decimal("0.5")
    assert btc.locked == Decimal("0")


def test_bybit_mapper_ticker() -> None:
    """Map linear ticker payload to Ticker model."""
    mapper = BybitExchangeMapper()
    raw_payload: ExchangePayload = {
        "symbol": "BTCUSDT",
        "lastPrice": "50000.5",
        "bid1Price": "50000.0",
        "ask1Price": "50001.0",
        "time": 1672531199000,
    }
    ticker = mapper.map_ticker(raw_payload)
    assert ticker.symbol == "BTCUSDT"
    assert ticker.last_price == Decimal("50000.5")
    assert ticker.bid_price == Decimal("50000.0")
    assert ticker.ask_price == Decimal("50001.0")
    assert ticker.timestamp.timestamp() == 1672531199.0


def test_bybit_mapper_candle() -> None:
    """Map Bybit kline sequence to Candle model."""
    mapper = BybitExchangeMapper()
    # [startTime, openPrice, highPrice, lowPrice, closePrice, volume, turnover]
    raw_seq = ("1672531200000", "50000", "50500", "49500", "50200", "12.5", "627500")
    candle = mapper.map_candle(
        raw_seq,
        symbol="BTCUSDT",
        interval=Interval.M5,
    )
    assert candle.symbol == "BTCUSDT"
    assert candle.interval == Interval.M5
    assert candle.open_price == Decimal("50000")
    assert candle.high_price == Decimal("50500")
    assert candle.low_price == Decimal("49500")
    assert candle.close_price == Decimal("50200")
    assert candle.volume == Decimal("12.5")


def test_bybit_mapper_order() -> None:
    """Map linear order payload to Order model."""
    mapper = BybitExchangeMapper()
    raw_payload: ExchangePayload = {
        "orderId": "bybit-ord-123",
        "symbol": "ETHUSDT",
        "side": "Buy",
        "orderType": "Limit",
        "orderStatus": "PartiallyFilled",
        "qty": "2.0",
        "cumExecQty": "1.0",
        "price": "3000.0",
        "createdTime": "1672531200000",
        "updatedTime": "1672531205000",
        "orderLinkId": "client-link-456",
    }
    order = mapper.map_order(raw_payload)
    assert order.order_id == "bybit-ord-123"
    assert order.symbol == "ETHUSDT"
    assert order.side is OrderSide.BUY
    assert order.order_type is OrderType.LIMIT
    assert order.status is OrderStatus.PARTIALLY_FILLED
    assert order.quantity == Decimal("2.0")
    assert order.executed_quantity == Decimal("1.0")
    assert order.price == Decimal("3000.0")
    assert order.client_order_id == "client-link-456"


def test_bybit_mapper_protection_orders() -> None:
    """Map Bybit conditional stop and take profit order payloads to types."""
    mapper = BybitExchangeMapper()
    sl_payload: ExchangePayload = {
        "orderId": "sl-ord-123",
        "symbol": "BTCUSDT",
        "side": "Sell",
        "orderType": "Market",
        "stopOrderType": "Stop",
        "triggerDirection": 2,
        "orderStatus": "Untriggered",
        "qty": "0.5",
        "cumExecQty": "0",
        "triggerPrice": "50000.0",
        "createdTime": "1672531200000",
        "orderLinkId": "bsl-algo-1",
    }
    sl_order = mapper.map_order(sl_payload)
    assert sl_order.order_type is OrderType.STOP_MARKET
    assert sl_order.stop_price == Decimal("50000.0")
    assert sl_order.client_order_id == "bsl-algo-1"

    tp_payload: ExchangePayload = {
        "orderId": "tp-ord-123",
        "symbol": "BTCUSDT",
        "side": "Sell",
        "orderType": "Market",
        "stopOrderType": "Stop",
        "triggerDirection": 1,
        "orderStatus": "Untriggered",
        "qty": "0.5",
        "cumExecQty": "0",
        "triggerPrice": "70000.0",
        "createdTime": "1672531200000",
        "orderLinkId": "btp-algo-1",
    }
    tp_order = mapper.map_order(tp_payload)
    assert tp_order.order_type is OrderType.TAKE_PROFIT_MARKET
    assert tp_order.stop_price == Decimal("70000.0")
    assert tp_order.client_order_id == "btp-algo-1"


def test_bybit_mapper_position() -> None:
    """Map linear position payload to Position model."""
    mapper = BybitExchangeMapper()
    raw_payload: ExchangePayload = {
        "symbol": "SOLUSDT",
        "side": "Buy",
        "size": "10.0",
        "avgPrice": "150.0",
        "markPrice": "155.0",
        "unrealisedPnl": "50.0",
        "leverage": "5",
        "createdTime": "1672531200000",
        "updatedTime": "1672531210000",
    }
    pos = mapper.map_position(raw_payload)
    assert pos.symbol == "SOLUSDT"
    assert pos.side is PositionSide.LONG
    assert pos.quantity == Decimal("10.0")
    assert pos.entry_price == Decimal("150.0")
    assert pos.current_price == Decimal("155.0")
    assert pos.unrealized_pnl == Decimal("50.0")
    assert pos.leverage == 5


def test_bybit_mapper_symbol_rules() -> None:
    """Map instrument-info payload to ExchangeSymbolRules model."""
    mapper = BybitExchangeMapper()
    raw_payload: ExchangePayload = {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "minOrderQty": "0.001",
            "maxOrderQty": "100.0",
            "qtyStep": "0.001",
        },
        "priceFilter": {
            "minPrice": "0.50",
            "maxPrice": "999999.00",
            "tickSize": "0.10",
        },
        "minNotionalValue": "5.0",
    }
    rules = mapper.map_symbol_rules(raw_payload)
    assert rules.symbol == "BTCUSDT"
    assert rules.market_min_quantity == Decimal("0.001")
    assert rules.market_max_quantity == Decimal("100.0")
    assert rules.market_quantity_step == Decimal("0.001")
    assert rules.price_tick_size == Decimal("0.10")
    assert rules.minimum_notional == Decimal("5.0")

    # When minNotionalValue is inside lotSizeFilter (real Bybit V5 format)
    v5_payload: ExchangePayload = {
        "symbol": "ADAUSDT",
        "lotSizeFilter": {
            "minOrderQty": "1",
            "maxOrderQty": "1500000",
            "qtyStep": "1",
            "minNotionalValue": "5",
        },
        "priceFilter": {
            "minPrice": "0.0001",
            "maxPrice": "99.9990",
            "tickSize": "0.0001",
        },
    }
    v5_rules = mapper.map_symbol_rules(v5_payload)
    assert v5_rules.minimum_notional == Decimal("5")


def test_bybit_mapper_market_universe_entry() -> None:
    """Map ticker 24h turnover to MarketUniverseEntry."""
    mapper = BybitExchangeMapper()
    raw_payload: ExchangePayload = {
        "symbol": "BTCUSDT",
        "turnover24h": "1500000000.50",
    }
    entry = mapper.map_market_universe_entry(raw_payload)
    assert entry.symbol == "BTCUSDT"
    assert entry.quote_volume == Decimal("1500000000.50")


# =============================================================================
# Futures Client Operations Tests
# =============================================================================
@pytest.mark.asyncio
async def test_bybit_futures_client_order_operations() -> None:
    """Test BybitFuturesExchangeClient create, cancel, and get order calls."""
    rest = MockBybitRestClient()
    mapper = BybitExchangeMapper()
    client = BybitFuturesExchangeClient(rest=rest, mapper=mapper)

    # 1. create_order
    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"orderId": "bybit-test-101"},
    }
    order = await client.create_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
        client_order_id="cid-001",
    )
    assert ("POST", "/v5/order/create") in rest.history
    assert order.symbol == "BTCUSDT"
    assert order.side is OrderSide.BUY

    # 2. create_protection_orders
    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"orderId": "sl-001"},
    }
    prot_orders = await client.create_protection_orders(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("0.1"),
        stop_loss=Decimal("48000"),
        take_profit=Decimal("55000"),
        stop_loss_client_algo_id="sl-algo-1",
        take_profit_client_algo_id="tp-algo-1",
    )
    assert len(prot_orders) == 2
    assert prot_orders[0].order_type is OrderType.STOP_MARKET
    assert prot_orders[0].stop_price == Decimal("48000")
    assert prot_orders[1].order_type is OrderType.TAKE_PROFIT_MARKET
    assert prot_orders[1].stop_price == Decimal("55000")

    # 3. cancel_order
    rest.canned_response = {"retCode": 0, "retMsg": "OK", "result": {}}
    cancelled = await client.cancel_order(symbol="BTCUSDT", order_id="bybit-test-101")
    assert rest.last_path == "/v5/order/cancel"
    assert cancelled.status is OrderStatus.CANCELED


@pytest.mark.asyncio
async def test_bybit_futures_client_positions_and_leverage() -> None:
    """Test BybitFuturesExchangeClient get_positions and set_leverage."""
    rest = MockBybitRestClient()
    mapper = BybitExchangeMapper()
    client = BybitFuturesExchangeClient(rest=rest, mapper=mapper)

    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "0.5",
                    "avgPrice": "50000",
                    "markPrice": "51000",
                    "unrealisedPnl": "500",
                    "leverage": "10",
                    "createdTime": "1672531200000",
                    "updatedTime": "1672531210000",
                },
                {
                    "symbol": "ETHUSDT",
                    "side": "None",
                    "size": "0",  # Zero position should be skipped
                    "avgPrice": "0",
                    "markPrice": "3000",
                    "unrealisedPnl": "0",
                    "leverage": "10",
                    "createdTime": "1672531200000",
                    "updatedTime": "1672531210000",
                },
            ]
        },
    }

    positions = await client.get_positions(symbol="BTCUSDT")
    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].quantity == Decimal("0.5")
    assert positions[0].leverage == 10

    # set_leverage
    rest.canned_response = {"retCode": 0, "retMsg": "OK", "result": {}}
    await client.set_leverage(symbol="BTCUSDT", leverage=20)
    assert rest.last_path == "/v5/position/set-leverage"
    assert rest.last_data is not None
    assert rest.last_data["buyLeverage"] == "20"

    # get_trades_for_order
    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                {
                    "execId": "trade-1",
                    "orderId": "order-123",
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "execPrice": "50000",
                    "execQty": "0.1",
                    "execFee": "0.05",
                    "feeCurrency": "USDT",
                    "execTime": "1672531200000",
                }
            ]
        },
    }
    order_trades = await client.get_trades_for_order(
        symbol="BTCUSDT",
        order_id="order-123",
    )
    assert len(order_trades) == 1
    assert order_trades[0].order_id == "order-123"
    assert order_trades[0].quantity == Decimal("0.1")

    # get_trades_for_order with closed-pnl enrichment
    rest.canned_responses = [
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "execId": "trade-2",
                        "orderId": "exit-456",
                        "symbol": "BTCUSDT",
                        "side": "Sell",
                        "execPrice": "51000",
                        "execQty": "0.1",
                        "execFee": "0.05",
                        "feeCurrency": "USDT",
                        "execTime": "1672531300000",
                    }
                ]
            },
        },
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "orderId": "exit-456",
                        "closedPnl": "25.50",
                    }
                ]
            },
        },
    ]
    exit_trades = await client.get_trades_for_order(
        symbol="BTCUSDT",
        order_id="exit-456",
    )
    assert len(exit_trades) == 1
    assert exit_trades[0].order_id == "exit-456"
    assert exit_trades[0].realized_pnl == Decimal("25.50")

    # verify_mainnet_readiness
    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"list": [{"accountType": "UNIFIED", "coin": []}]},
    }
    await client.verify_mainnet_readiness()

    # verify_mainnet_symbol_readiness with 20x leverage capped by symbol max
    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "lotSizeFilter": {
                        "minOrderQty": "0.001",
                        "maxOrderQty": "100",
                        "qtyStep": "0.001",
                    },
                    "priceFilter": {
                        "minPrice": "0.1",
                        "maxPrice": "100000",
                        "tickSize": "0.1",
                    },
                    "leverageFilter": {
                        "minLeverage": "1",
                        "maxLeverage": "50.00",
                        "leverageStep": "0.01",
                    },
                }
            ]
        },
    }
    await client.verify_mainnet_symbol_readiness(
        symbol="BTCUSDT",
        maximum_leverage=20,
        entry_notional=Decimal("100"),
    )
    assert ("POST", "/v5/position/set-leverage") in rest.history
    assert rest.last_data == {
        "category": "linear",
        "symbol": "BTCUSDT",
        "buyLeverage": "20",
        "sellLeverage": "20",
    }

    # verify_mainnet_symbol_readiness with lower symbol cap (e.g. 5x)
    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                {
                    "symbol": "AIOUSDT",
                    "lotSizeFilter": {
                        "minOrderQty": "1",
                        "maxOrderQty": "100000",
                        "qtyStep": "1",
                    },
                    "priceFilter": {
                        "minPrice": "0.0001",
                        "maxPrice": "10",
                        "tickSize": "0.0001",
                    },
                    "leverageFilter": {
                        "minLeverage": "1",
                        "maxLeverage": "5.00",
                        "leverageStep": "0.01",
                    },
                }
            ]
        },
    }
    await client.verify_mainnet_symbol_readiness(
        symbol="AIOUSDT",
        maximum_leverage=20,
        entry_notional=Decimal("10"),
    )
    assert rest.last_data == {
        "category": "linear",
        "symbol": "AIOUSDT",
        "buyLeverage": "5",
        "sellLeverage": "5",
    }


# =============================================================================
# Stream Client Parsing Tests
# =============================================================================
def test_bybit_stream_client_parsing() -> None:
    """Test BybitStreamClient message parsing and queue dispatch."""
    mapper = BybitExchangeMapper()
    stream = MockBybitStreamClient(
        websocket_url="wss://stream.bybit.com/v5/public/linear",
        mapper=mapper,
    )

    # Attach queues
    ticker_queue: asyncio.Queue[object] = asyncio.Queue()
    stream.attach_topic_queue("tickers.BTCUSDT", ticker_queue)

    # Simulate incoming ticker payload
    raw_ticker_msg = (
        '{"topic":"tickers.BTCUSDT","type":"snapshot",'
        '"data":{"symbol":"BTCUSDT","lastPrice":"50100","bid1Price":"50090",'
        '"ask1Price":"50110","time":1672531200000}}'
    )
    stream.inject_raw_message(raw_ticker_msg)
    assert not ticker_queue.empty()
    item = ticker_queue.get_nowait()
    assert isinstance(item, Ticker)
    assert item.symbol == "BTCUSDT"
    assert item.last_price == Decimal("50100")

    # Simulate kline payload
    kline_queue: asyncio.Queue[object] = asyncio.Queue()
    stream.attach_topic_queue("kline.15.BTCUSDT", kline_queue)
    raw_kline_msg = (
        '{"topic":"kline.15.BTCUSDT",'
        '"data":[{"start":1672531200000,"end":1672532100000,"open":"50000",'
        '"close":"50200","high":"50300","low":"49900","volume":"10"}]}'
    )
    stream.inject_raw_message(raw_kline_msg)
    assert not kline_queue.empty()
    candle_item = kline_queue.get_nowait()
    assert isinstance(candle_item, Candle)
    assert candle_item.symbol == "BTCUSDT"
    assert candle_item.close_price == Decimal("50200")


@pytest.mark.asyncio
async def test_bybit_get_market_universe_filters_zero_volume() -> None:
    """Ensure get_market_universe only includes symbols with positive turnover."""
    rest = MockBybitRestClient()
    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": "linear",
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "turnover24h": "1000000.5",
                    "volume24h": "20.0",
                },
                {
                    "symbol": "100000TSTSATSUSDT",
                    "turnover24h": "0.0000",
                    "volume24h": "0.0000",
                },
                {
                    "symbol": "ETHUSDT",
                    "turnover24h": "500000.0",
                    "volume24h": "150.0",
                },
                {
                    "symbol": "BTCUSDC",
                    "turnover24h": "200000.0",
                    "volume24h": "4.0",
                },
            ],
        },
    }
    mapper = BybitExchangeMapper()
    client = BybitFuturesExchangeClient(rest=rest, mapper=mapper)
    entries = await client.get_market_universe(quote_asset="USDT")
    assert len(entries) == 2
    assert all(isinstance(entry, MarketUniverseEntry) for entry in entries)
    assert entries[0].symbol == "BTCUSDT"
    assert entries[0].quote_volume == Decimal("1000000.5")
    assert entries[1].symbol == "ETHUSDT"
    assert entries[1].quote_volume == Decimal("500000.0")


@pytest.mark.asyncio
async def test_bybit_futures_client_open_orders_default_settle_coin() -> None:
    """Ensure get_open_orders and get_open_protection_orders send settleCoin=USDT."""
    rest = MockBybitRestClient()
    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"list": []},
    }
    client = BybitFuturesExchangeClient(rest=rest, mapper=BybitExchangeMapper())

    await client.get_open_orders(symbol=None)
    assert rest.last_params is not None
    assert rest.last_params.get("settleCoin") == "USDT"

    await client.get_open_protection_orders(symbol=None)
    assert rest.last_params is not None
    assert rest.last_params.get("settleCoin") == "USDT"


@pytest.mark.asyncio
async def test_bybit_client_get_candles_validation() -> None:
    """Ensure get_candles validates limits and timestamps."""
    rest = MockBybitRestClient()
    client = BybitExchangeClient(rest=rest, mapper=BybitExchangeMapper())

    with pytest.raises(ValueError, match="Candle limit must be greater than zero"):
        await client.get_candles(
            symbol="BTCUSDT",
            interval=Interval.M5,
            limit=0,
        )

    t1 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    with pytest.raises(
        ValueError, match="Candle start time must not be after end time"
    ):
        await client.get_candles(
            symbol="BTCUSDT",
            interval=Interval.M5,
            limit=10,
            start_time=t1,
            end_time=t2,
        )


@pytest.mark.asyncio
async def test_bybit_client_get_candles_normal() -> None:
    """Ensure get_candles normalizes and sorts candles oldest to newest."""
    rest = MockBybitRestClient()
    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                [
                    "1788229500000",
                    "60000",
                    "60100",
                    "59900",
                    "60050",
                    "10",
                    "600000",
                ],
                [
                    "1788229200000",
                    "59950",
                    "60020",
                    "59900",
                    "60000",
                    "8",
                    "480000",
                ],
            ]
        },
    }
    client = BybitExchangeClient(rest=rest, mapper=BybitExchangeMapper())
    candles = await client.get_candles(
        symbol="btcusdt",
        interval=Interval.M5,
        limit=2,
    )
    assert len(candles) == 2
    # Oldest first
    assert candles[0].open_time < candles[1].open_time
    assert candles[0].symbol == "BTCUSDT"
    assert candles[1].symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_bybit_client_get_candles_pagination_over_1000() -> None:
    """Ensure get_candles paginates backwards when limit > 1000."""
    rest = MockBybitRestClient()
    # Page 1: 1000 candles (newest 1788229500000 to oldest 1788200000000)
    page1_list = [
        [
            str(1788200000000 + i * 300000),
            "60000",
            "60100",
            "59900",
            "60050",
            "10",
            "600000",
        ]
        for i in range(999, -1, -1)
    ]
    # Page 2: 200 candles older than page 1 oldest (1788200000000)
    page2_list = [
        [
            str(1788100000000 + i * 300000),
            "59000",
            "59100",
            "58900",
            "59050",
            "10",
            "590000",
        ]
        for i in range(199, -1, -1)
    ]
    rest.canned_responses = [
        {"retCode": 0, "retMsg": "OK", "result": {"list": page1_list}},
        {"retCode": 0, "retMsg": "OK", "result": {"list": page2_list}},
    ]
    client = BybitExchangeClient(rest=rest, mapper=BybitExchangeMapper())
    candles = await client.get_candles(
        symbol="BTCUSDT",
        interval=Interval.M5,
        limit=1200,
    )
    assert len(candles) == 1200
    assert len(rest.history) == 2
    assert candles[0].open_time < candles[-1].open_time


@pytest.mark.asyncio
async def test_bybit_futures_client_create_order_rejected() -> None:
    """Ensure BybitRestResponseError translates to ExchangeOrderRejectedError."""
    rest = MockBybitRestClient()
    rest.canned_response = {
        "retCode": 110126,
        "retMsg": "You must sign the required agreement before trading this contract.",
        "result": {},
    }
    client = BybitFuturesExchangeClient(rest=rest, mapper=BybitExchangeMapper())

    with pytest.raises(ExchangeOrderRejectedError, match="110126"):
        await client.create_order(
            symbol="SHOPUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.02"),
            client_order_id="cid-rejected-1",
        )


@pytest.mark.asyncio
async def test_bybit_futures_client_create_order_unknown_outcome() -> None:
    """Ensure timeout/runtime errors translate to ExchangeOrderOutcomeUnknownError."""
    rest = MockBybitRestClient()
    rest.post_exception = TimeoutError("Request timed out waiting for Bybit")
    client = BybitFuturesExchangeClient(rest=rest, mapper=BybitExchangeMapper())

    with pytest.raises(ExchangeOrderOutcomeUnknownError):
        await client.create_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.02"),
            client_order_id="cid-timeout-1",
        )


@pytest.mark.asyncio
async def test_bybit_futures_client_order_not_found_raises_domain_exception() -> None:
    """Ensure missing orders raise ExchangeOrderNotFoundError instead of ValueError."""
    rest = MockBybitRestClient()
    rest.canned_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"list": []},
    }
    client = BybitFuturesExchangeClient(rest=rest, mapper=BybitExchangeMapper())

    with pytest.raises(ExchangeOrderNotFoundError, match="ord-1"):
        await client.get_order(symbol="BTCUSDT", order_id="ord-1")

    with pytest.raises(ExchangeOrderNotFoundError, match="cid-1"):
        await client.get_order_by_client_order_id(
            symbol="BTCUSDT", client_order_id="cid-1"
        )

    with pytest.raises(ExchangeOrderNotFoundError, match="pid-1"):
        await client.get_protection_order_by_client_id(
            symbol="BTCUSDT", client_id="pid-1"
        )


def test_bybit_stream_ticker_delta_merges_snapshot() -> None:
    """Ensure Bybit stream merges ticker deltas into cached snapshot."""
    client = BybitStreamClient(
        websocket_url="wss://stream.bybit.com/v5/public/linear",
        mapper=BybitExchangeMapper(),
    )

    # Snapshot with full fields
    snapshot = json.dumps(
        {
            "topic": "tickers.BTCUSDT",
            "type": "snapshot",
            "data": {
                "symbol": "BTCUSDT",
                "lastPrice": "50000.0",
                "bid1Price": "49999.0",
                "ask1Price": "50001.0",
            },
        }
    )
    client.handle_message(snapshot)
    cached = client.get_cached_ticker("BTCUSDT")
    assert cached is not None
    assert cached.get("lastPrice") == "50000.0"

    # Delta missing lastPrice
    delta = json.dumps(
        {
            "topic": "tickers.BTCUSDT",
            "type": "delta",
            "data": {
                "symbol": "BTCUSDT",
                "indexPrice": "50005.0",
                "bid1Price": "49999.5",
            },
        }
    )
    client.handle_message(delta)
    cached_after = client.get_cached_ticker("BTCUSDT")
    assert cached_after is not None
    assert cached_after.get("lastPrice") == "50000.0"
    assert cached_after.get("bid1Price") == "49999.5"


def test_bybit_mapper_stream_ticker_fallback() -> None:
    """Ensure map_stream_ticker falls back to markPrice if lastPrice missing."""
    mapper = BybitExchangeMapper()
    payload: ExchangePayload = {
        "symbol": "BTCUSDT",
        "markPrice": "50000.0",
        "bid1Price": "49999.0",
        "ask1Price": "50001.0",
        "time": "1672531200000",
    }
    ticker = mapper.map_stream_ticker(payload)
    assert ticker.last_price == Decimal("50000.0")
