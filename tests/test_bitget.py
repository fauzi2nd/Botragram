"""
Botragram

Description:
    Bitget exchange client, mapper, and factory wiring tests.

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
from datetime import UTC, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import cast

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
from botragram.exceptions import ExchangeError, ExchangeOrderNotFoundError
from botragram.exchanges.base.rest import (
    JsonResponse,
    QueryParams,
    RequestHeaders,
)
from botragram.exchanges.bitget.client import BitgetClient
from botragram.exchanges.bitget.futures_client import BitgetFuturesExchangeClient
from botragram.exchanges.bitget.mapper import BitgetExchangeMapper
from botragram.exchanges.bitget.rest import BitgetRestClient, BitgetRestResponseError
from botragram.exchanges.bitget.stream import BitgetStreamClient
from botragram.exchanges.factory import ExchangeFactory
from botragram.models import Position


# =============================================================================
# Test Mocks
# =============================================================================
class MockBitgetRestClient(BitgetRestClient):
    """Test subclass recording requests and returning canned responses."""

    def __init__(self) -> None:
        super().__init__(
            base_url="https://api.bitget.com",
            api_key="mock-api-key",
            api_secret="mock-api-secret",
            passphrase="mock-passphrase",
        )
        self.history: list[tuple[str, str]] = []
        self.last_method = ""
        self.last_path = ""
        self.last_params: QueryParams | None = None
        self.last_data: dict[str, object] | None = None
        self.canned_response: JsonResponse = {
            "code": "00000",
            "msg": "success",
            "data": {},
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
        if self.canned_responses:
            response = self.canned_responses.pop(0)
        else:
            response = self.canned_response
        return self._validate_response_envelope(response)

    def test_prepare_headers(
        self, *, method: str, path: str, payload_str: str
    ) -> dict[str, str]:
        """Expose protected header preparation for unit tests."""
        return self._prepare_headers(
            authenticated=True, method=method, path=path, payload_str=payload_str
        )

    @staticmethod
    def test_validate_envelope(payload: JsonResponse) -> JsonResponse:
        """Expose protected response envelope validation for unit tests."""
        return MockBitgetRestClient._validate_response_envelope(payload)


# =============================================================================
# Factory Wiring Tests
# =============================================================================
def test_exchange_factory_creates_bitget_components() -> None:
    """ExchangeFactory must create proper Bitget clients."""
    rest_url = "https://api.bitget.com"
    ws_url = "wss://ws-manager.bitget.com/v2/ws/public"

    rest = ExchangeFactory.create_rest_client(
        exchange_type=ExchangeType.BITGET,
        base_url=rest_url,
        api_key="test-key",
        api_secret="test-secret",
        passphrase="test-passphrase",
    )
    assert isinstance(rest, BitgetRestClient)
    assert rest.has_credentials

    futures_client = ExchangeFactory.create_exchange_client(
        exchange_type=ExchangeType.BITGET,
        rest_client=rest,
        market_type=MarketType.FUTURES,
    )
    assert isinstance(futures_client, BitgetFuturesExchangeClient)

    stream = ExchangeFactory.create_stream_client(
        exchange_type=ExchangeType.BITGET,
        base_url=ws_url,
    )
    assert isinstance(stream, BitgetStreamClient)

    client, stream_bundle = ExchangeFactory.create(
        exchange_type=ExchangeType.BITGET,
        rest_base_url=rest_url,
        websocket_base_url=ws_url,
        api_key="test-key",
        api_secret="test-secret",
        passphrase="test-passphrase",
        market_type=MarketType.FUTURES,
    )
    assert isinstance(client, BitgetFuturesExchangeClient)
    assert isinstance(stream_bundle, BitgetStreamClient)


def test_exchange_factory_rejects_bitget_spot() -> None:
    """Bitget SPOT is not supported currently."""
    rest = ExchangeFactory.create_rest_client(
        exchange_type=ExchangeType.BITGET,
        base_url="https://api.bitget.com",
    )
    with pytest.raises(ValueError, match="only supports FUTURES"):
        ExchangeFactory.create_exchange_client(
            exchange_type=ExchangeType.BITGET,
            rest_client=rest,
            market_type=MarketType.SPOT,
        )


# =============================================================================
# REST Client & Auth Tests
# =============================================================================
def test_bitget_rest_client_auth_headers() -> None:
    """Verify HMAC-SHA256 signature and required headers."""
    client = MockBitgetRestClient()
    headers = client.test_prepare_headers(
        method="GET",
        path="/api/v2/mix/account/accounts?productType=USDT-FUTURES",
        payload_str="",
    )

    assert "ACCESS-KEY" in headers
    assert headers["ACCESS-KEY"] == "mock-api-key"
    assert "ACCESS-SIGN" in headers
    assert "ACCESS-TIMESTAMP" in headers
    assert "ACCESS-PASSPHRASE" in headers
    assert headers["ACCESS-PASSPHRASE"] == "mock-passphrase"


def test_bitget_rest_client_validate_envelope_success() -> None:
    """Return payload when response code is '00000' or 0."""
    payload: JsonResponse = {
        "code": "00000",
        "msg": "success",
        "data": {"foo": "bar"},
    }
    validated = MockBitgetRestClient.test_validate_envelope(payload)
    assert validated == payload


def test_bitget_rest_client_validate_envelope_error() -> None:
    """Raise ExchangeError when response code is non-zero."""
    payload: JsonResponse = {
        "code": "40017",
        "msg": "Parameter error",
    }
    with pytest.raises(ExchangeError, match="Bitget REST API error 40017"):
        MockBitgetRestClient.test_validate_envelope(payload)


# =============================================================================
# Mapper Tests
# =============================================================================
def test_bitget_mapper_map_candle() -> None:
    """Map standard Bitget candle list [ts, open, high, low, close, vol, quoteVol]."""
    mapper = BitgetExchangeMapper()
    payload = (
        "1700000000000",
        "50000.5",
        "51000.0",
        "49500.0",
        "50800.0",
        "123.456",
        "6200000.0",
    )
    candle = mapper.map_candle(payload, symbol="BTCUSDT", interval=Interval.M5)

    assert candle.symbol == "BTCUSDT"
    assert candle.interval is Interval.M5
    assert candle.open_price == Decimal("50000.5")
    assert candle.high_price == Decimal("51000.0")
    assert candle.low_price == Decimal("49500.0")
    assert candle.close_price == Decimal("50800.0")
    assert candle.volume == Decimal("123.456")
    assert candle.open_time == datetime.fromtimestamp(1700000000, tz=timezone.utc)


def test_bitget_mapper_map_candle_invalid_length() -> None:
    """Reject candle payloads with insufficient elements."""
    mapper = BitgetExchangeMapper()
    with pytest.raises(ValueError, match="at least 6 elements"):
        mapper.map_candle(
            ("1700000000000", "50000.5"), symbol="BTCUSDT", interval=Interval.M1
        )


def test_bitget_mapper_map_ticker() -> None:
    """Map Bitget ticker payload into Ticker model."""
    mapper = BitgetExchangeMapper()
    payload = {
        "symbol": "BTCUSDT",
        "lastPr": "50000.5",
        "bidPr": "50000.0",
        "askPr": "50001.0",
        "ts": "1700000000000",
        "fundingRate": "0.0001",
    }
    ticker = mapper.map_ticker(payload)
    assert ticker.symbol == "BTCUSDT"
    assert ticker.last_price == Decimal("50000.5")
    assert ticker.bid_price == Decimal("50000.0")
    assert ticker.ask_price == Decimal("50001.0")
    assert ticker.funding_rate == Decimal("0.0001")


def test_bitget_mapper_map_order() -> None:
    """Map Bitget order payload into Order model."""
    mapper = BitgetExchangeMapper()
    payload = {
        "orderId": "1234567890",
        "clientOid": "bot-order-001",
        "symbol": "BTCUSDT",
        "side": "buy",
        "orderType": "limit",
        "status": "filled",
        "price": "50000.0",
        "size": "0.100",
        "baseVolume": "0.100",
        "cTime": "1700000000000",
        "uTime": "1700000005000",
    }
    order = mapper.map_order(payload)
    assert order.order_id == "1234567890"
    assert order.client_order_id == "bot-order-001"
    assert order.symbol == "BTCUSDT"
    assert order.side is OrderSide.BUY
    assert order.order_type is OrderType.LIMIT
    assert order.status is OrderStatus.FILLED
    assert order.price == Decimal("50000.0")
    assert order.quantity == Decimal("0.100")
    assert order.executed_quantity == Decimal("0.100")


def test_bitget_mapper_map_position() -> None:
    """Map Bitget position payload into Position model."""
    mapper = BitgetExchangeMapper()
    payload = {
        "symbol": "BTCUSDT",
        "holdSide": "long",
        "total": "0.500",
        "openPriceAvg": "48000.0",
        "markPrice": "50000.0",
        "unrealizedPL": "1000.0",
        "leverage": "10",
        "cTime": "1700000000000",
    }
    pos = mapper.map_position(payload)
    assert pos.symbol == "BTCUSDT"
    assert pos.side is PositionSide.LONG
    assert pos.quantity == Decimal("0.500")
    assert pos.entry_price == Decimal("48000.0")
    assert pos.current_price == Decimal("50000.0")
    assert pos.unrealized_pnl == Decimal("1000.0")
    assert pos.leverage == 10


def test_bitget_mapper_map_account() -> None:
    """Map Bitget balance list into Account model."""
    mapper = BitgetExchangeMapper()
    payload = {
        "data": [
            {
                "marginCoin": "USDT",
                "available": "1500.50",
                "frozen": "200.00",
            },
            {
                "marginCoin": "BTC",
                "available": "0.05",
                "frozen": "0.00",
            },
        ]
    }
    account = mapper.map_account(payload)
    assert len(account.balances) == 2
    usdt = next(b for b in account.balances if b.asset == "USDT")
    assert usdt.free == Decimal("1500.50")
    assert usdt.locked == Decimal("200.00")


def test_bitget_mapper_map_trade() -> None:
    """Map Bitget fill trade payload into Trade model."""
    mapper = BitgetExchangeMapper()
    payload = {
        "tradeId": "trade-999",
        "orderId": "order-123",
        "symbol": "BTCUSDT",
        "side": "buy",
        "price": "50000.0",
        "size": "0.10",
        "fee": "0.05",
        "feeCurrency": "USDT",
        "cTime": "1700000000000",
    }
    trade = mapper.map_trade(payload)
    assert trade.trade_id == "trade-999"
    assert trade.order_id == "order-123"
    assert trade.symbol == "BTCUSDT"
    assert trade.side is OrderSide.BUY
    assert trade.price == Decimal("50000.0")
    assert trade.quantity == Decimal("0.10")
    assert trade.quote_quantity == Decimal("5000.000")
    assert trade.fee == Decimal("0.05")
    assert trade.fee_asset == "USDT"


def test_bitget_mapper_intervals() -> None:
    """Verify supported and unsupported interval mapping."""
    mapper = BitgetExchangeMapper()
    assert mapper.to_exchange_interval(Interval.M1) == "1m"
    assert mapper.to_exchange_interval(Interval.M5) == "5m"
    assert mapper.to_exchange_interval(Interval.M15) == "15m"
    assert mapper.to_exchange_interval(Interval.H1) == "1H"
    assert mapper.to_exchange_interval(Interval.H4) == "4H"
    assert mapper.to_exchange_interval(Interval.D1) == "1D"

    with pytest.raises(ValueError, match="Unsupported Bitget interval"):
        mapper.to_exchange_interval(Interval.M7)


# =============================================================================
# Futures Exchange Client Tests
# =============================================================================
@pytest.mark.asyncio
async def test_bitget_futures_exchange_client_get_ticker() -> None:
    """Verify get_ticker queries mix ticker endpoint."""
    rest = MockBitgetRestClient()
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "BTCUSDT",
                "lastPr": "60000.0",
                "bidPr": "59999.0",
                "askPr": "60001.0",
                "ts": "1700000000000",
                "fundingRate": "0.0001",
            }
        ],
    }
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())
    ticker = await client.get_ticker(symbol="BTCUSDT")

    assert ticker.symbol == "BTCUSDT"
    assert ticker.last_price == Decimal("60000.0")
    assert rest.last_path == "/api/v2/mix/market/ticker"
    assert rest.last_params == {
        "symbol": "BTCUSDT",
        "productType": "USDT-FUTURES",
    }


@pytest.mark.asyncio
async def test_bitget_futures_exchange_client_get_candles() -> None:
    """Verify get_candles queries mix candles endpoint."""
    rest = MockBitgetRestClient()
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            [
                "1700000000000",
                "60000.0",
                "60500.0",
                "59900.0",
                "60200.0",
                "10.5",
                "630000.0",
            ]
        ],
    }
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())
    candles = await client.get_candles(symbol="BTCUSDT", interval=Interval.M5, limit=1)

    assert len(candles) == 1
    assert candles[0].close_price == Decimal("60200.0")
    assert rest.last_path == "/api/v2/mix/market/candles"


@pytest.mark.asyncio
async def test_bitget_futures_exchange_client_verify_mainnet_readiness() -> None:
    """Verify readiness succeeds with credentials and fails without."""
    rest = MockBitgetRestClient()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())
    # Should succeed with mock credentials
    await client.verify_mainnet_readiness()

    # Should fail when missing passphrase
    unauthenticated_rest = BitgetRestClient(
        base_url="https://api.bitget.com",
        api_key="key",
        api_secret="secret",
        passphrase="",
    )
    unauth_client = BitgetFuturesExchangeClient(
        rest=unauthenticated_rest, mapper=BitgetExchangeMapper()
    )
    with pytest.raises(ExchangeError, match="credentials are required"):
        await unauth_client.verify_mainnet_readiness()


@pytest.mark.asyncio
async def test_bitget_futures_create_reduce_only_market_order() -> None:
    """Submit reduce-only market order on Bitget Futures with reduceOnly=YES."""
    rest = MockBitgetRestClient()
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {"orderId": "bg-pclose-1", "holdMode": "one_way_mode"},
    }
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    order = await client.create_reduce_only_market_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("0.5"),
        client_order_id="bg-client-1",
    )

    assert order.order_id == "bg-pclose-1"
    assert ("POST", "/api/v3/trade/place-order") in rest.history
    assert rest.last_data is not None
    assert rest.last_data.get("category") == "USDT-FUTURES"
    assert rest.last_data.get("orderType") == "market"
    assert rest.last_data.get("side") == "sell"
    assert rest.last_data.get("qty") == "0.5"
    assert rest.last_data.get("reduceOnly") == "YES"
    assert rest.last_data.get("clientOid") == "bg-client-1"

    with pytest.raises(ValueError, match="Order quantity must be greater than zero"):
        await client.create_reduce_only_market_order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("0"),
        )


@pytest.mark.asyncio
async def test_bitget_futures_v3_uta_operations() -> None:
    """Verify all V3 UTA endpoints, payloads, and responses."""
    rest = MockBitgetRestClient()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    # 1. get_account uses /api/v3/account/assets
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "list": [
                {
                    "coin": "USDT",
                    "available": "5000.00",
                    "frozen": "100.00",
                }
            ]
        },
    }
    account = await client.get_account()
    assert rest.last_path == "/api/v3/account/assets"
    assert len(account.balances) == 1
    assert account.balances[0].asset == "USDT"
    assert account.balances[0].free == Decimal("5000.00")

    # 2. get_positions uses /api/v3/position/current-position
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "list": [
                {
                    "symbol": "ETHUSDT",
                    "holdSide": "short",
                    "total": "2.0",
                    "openPriceAvg": "3000.0",
                    "markPrice": "2950.0",
                    "unrealizedPL": "100.0",
                    "leverage": "20",
                    "cTime": "1700000000000",
                }
            ]
        },
    }
    positions = await client.get_positions(symbol="ETHUSDT")
    assert rest.last_path == "/api/v3/position/current-position"
    assert rest.last_params == {
        "category": "USDT-FUTURES",
        "symbol": "ETHUSDT",
    }
    assert len(positions) == 1
    assert positions[0].symbol == "ETHUSDT"
    assert positions[0].side is PositionSide.SHORT
    assert positions[0].quantity == Decimal("2.0")

    # 3. cancel_order uses /api/v3/trade/cancel-order
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {},
    }
    await client.cancel_order(symbol="BTCUSDT", order_id="ord-99")
    assert ("POST", "/api/v3/trade/cancel-order") in rest.history
    assert rest.last_data == {
        "category": "USDT-FUTURES",
        "symbol": "BTCUSDT",
        "orderId": "ord-99",
    }

    # 4. cancel_all_orders uses /api/v3/trade/cancel-symbol-order
    rest.canned_responses = [
        # for get_open_orders
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "list": [
                    {
                        "orderId": "o1",
                        "symbol": "BTCUSDT",
                        "side": "buy",
                        "orderType": "limit",
                        "status": "live",
                        "qty": "0.1",
                        "cTime": "1700000000000",
                    }
                ]
            },
        },
        # for cancel-symbol-order
        {"code": "00000", "msg": "success", "data": {}},
    ]
    canceled = await client.cancel_all_orders(symbol="BTCUSDT")
    assert len(canceled) == 1
    assert rest.last_path == "/api/v3/trade/cancel-symbol-order"
    assert rest.last_data == {
        "category": "USDT-FUTURES",
        "symbol": "BTCUSDT",
    }

    # 5. create_protection_orders uses /api/v3/trade/place-strategy-order
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {"orderId": "strat-1"},
    }
    prot_orders = await client.create_protection_orders(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("0.1"),
        stop_loss=Decimal("59000.0"),
        take_profit=Decimal("65000.0"),
        stop_loss_client_algo_id="sl-algo-1",
        take_profit_client_algo_id="tp-algo-1",
    )
    assert len(prot_orders) == 2
    assert rest.last_path == "/api/v3/trade/place-strategy-order"
    assert rest.last_data is not None
    assert rest.last_data.get("category") == "USDT-FUTURES"
    assert rest.last_data.get("type") == "tpsl"

    # 6. set_leverage uses /api/v3/account/set-leverage
    rest.canned_response = {"code": "00000", "msg": "success", "data": {}}
    await client.set_leverage(symbol="BTCUSDT", leverage=25, hold_side="long")
    assert rest.last_path == "/api/v3/account/set-leverage"
    assert rest.last_data == {
        "category": "USDT-FUTURES",
        "symbol": "BTCUSDT",
        "leverage": "25",
        "posSide": "long",
        "marginMode": "crossed",
    }


def test_settings_manager_loads_bitget_market_type(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify SettingsManager parses BITGET_MARKET_TYPE and strips credentials."""
    monkeypatch.delenv("BOTRAGRAM_ENV_FILE", raising=False)
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)
    monkeypatch.setenv("ACTIVE_EXCHANGE", "BITGET")
    monkeypatch.setenv("BITGET_MARKET_TYPE", "FUTURES")
    monkeypatch.setenv("BITGET_API_KEY", "  test-key  ")
    monkeypatch.setenv("BITGET_API_SECRET", "  test-secret  ")
    monkeypatch.setenv("BITGET_PASSPHRASE", "  test-passphrase  ")
    monkeypatch.setenv("BITGET_TESTNET", "false")

    from botragram.app.environment_provider import EnvironmentProvider
    from botragram.app.settings_manager import SettingsManager

    env_provider = EnvironmentProvider(env_path=str(tmp_path / "missing.env"))
    settings = SettingsManager(
        environment_provider=env_provider
    ).load_exchange_settings()
    assert settings.exchange is ExchangeType.BITGET
    assert settings.market_type is MarketType.FUTURES
    assert settings.api_key == "test-key"
    assert settings.api_secret == "test-secret"
    assert settings.passphrase == "test-passphrase"
    assert not settings.testnet


@pytest.mark.asyncio
async def test_bitget_futures_exchange_client_get_trades_for_order() -> None:
    """Verify get_trades_for_order queries fills endpoint with category and orderId."""
    rest = MockBitgetRestClient()
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "tradeId": "t1",
                "orderId": "ord-123",
                "symbol": "BTCUSDT",
                "side": "buy",
                "price": "50000.0",
                "size": "0.1",
                "fee": "0.02",
                "feeCurrency": "USDT",
                "cTime": "1700000000000",
                "pnl": "15.5",
            },
            {
                "tradeId": "t2",
                "orderId": "ord-other",
                "symbol": "BTCUSDT",
                "side": "buy",
                "price": "50000.0",
                "size": "0.1",
                "fee": "0.02",
                "feeCurrency": "USDT",
                "cTime": "1700000000000",
            },
        ],
    }
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())
    trades = await client.get_trades_for_order(symbol="BTCUSDT", order_id="ord-123")

    assert len(trades) == 1
    assert trades[0].trade_id == "t1"
    assert trades[0].order_id == "ord-123"
    assert trades[0].price == Decimal("50000.0")
    assert trades[0].realized_pnl == Decimal("15.5")
    assert rest.last_path == "/api/v3/trade/fills"
    assert rest.last_params == {
        "category": "USDT-FUTURES",
        "symbol": "BTCUSDT",
        "orderId": "ord-123",
        "limit": 100,
    }


@pytest.mark.asyncio
async def test_bitget_futures_client_close_position_exact() -> None:
    """Verify close_position_exact places reduce-only market order with clientOid."""
    rest = MockBitgetRestClient()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    # 1. Close Short position (like ASTERUSDT short) -> buy, posSide=short
    rest.canned_responses = [
        # get_hold_mode
        {
            "code": "00000",
            "msg": "success",
            "data": {"productType": "USDT-FUTURES", "posMode": "hedge_mode"},
        },
        # place-order
        {
            "code": "00000",
            "msg": "success",
            "data": {"orderId": "ord-close-short"},
        },
        # get_order
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "orderId": "ord-close-short",
                "clientOid": "bop-attempt-short",
                "symbol": "ASTERUSDT",
                "side": "buy",
                "orderType": "market",
                "status": "live",
                "size": "33",
                "cTime": "1700000000000",
            },
        },
    ]

    now = datetime.now(UTC)
    short_pos = Position(
        symbol="ASTERUSDT",
        side=PositionSide.SHORT,
        quantity=Decimal("33"),
        entry_price=Decimal("0.7443"),
        current_price=Decimal("0.7400"),
        leverage=8,
        unrealized_pnl=Decimal("0.14"),
        opened_at=now,
        updated_at=now,
    )
    closed = await client.close_position_exact(
        position=short_pos,
        client_order_id="bop-attempt-short",
    )

    assert closed.order_id == "ord-close-short"
    assert closed.client_order_id == "bop-attempt-short"
    assert closed.symbol == "ASTERUSDT"
    assert closed.side is OrderSide.BUY
    assert closed.order_type is OrderType.MARKET
    assert closed.quantity == Decimal("33")

    # Verify REST call parameters for placing order
    place_calls = [c for c in rest.history if c[1] == "/api/v3/trade/place-order"]
    assert len(place_calls) == 1
    assert rest.last_data is not None
    assert rest.last_data["symbol"] == "ASTERUSDT"
    assert rest.last_data["side"] == "buy"
    assert rest.last_data["orderType"] == "market"
    assert rest.last_data["qty"] == "33"
    assert rest.last_data["clientOid"] == "bop-attempt-short"
    assert rest.last_data["posSide"] == "short"

    # 2. Close Long position -> sell, posSide=long
    rest.history.clear()
    rest.canned_responses = [
        # place-order (hold_mode is cached)
        {
            "code": "00000",
            "msg": "success",
            "data": {"orderId": "ord-close-long"},
        },
        # get_order
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "orderId": "ord-close-long",
                "clientOid": "bop-attempt-long",
                "symbol": "BTCUSDT",
                "side": "sell",
                "orderType": "market",
                "status": "live",
                "size": "0.5",
                "cTime": "1700000000000",
            },
        },
    ]

    long_pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("0.5"),
        entry_price=Decimal("60000"),
        current_price=Decimal("61000"),
        leverage=10,
        unrealized_pnl=Decimal("500"),
        opened_at=now,
        updated_at=now,
    )
    closed_long = await client.close_position_exact(
        position=long_pos,
        client_order_id="bop-attempt-long",
    )
    assert closed_long.order_id == "ord-close-long"
    assert closed_long.client_order_id == "bop-attempt-long"
    assert closed_long.side is OrderSide.SELL
    assert rest.last_data is not None
    assert rest.last_data["symbol"] == "BTCUSDT"
    assert rest.last_data["side"] == "sell"
    assert rest.last_data["posSide"] == "long"


@pytest.mark.asyncio
async def test_bitget_futures_create_order_hedge_mode() -> None:
    """Verify hedge mode sets posSide=long for buy and posSide=short for sell."""
    rest = MockBitgetRestClient()
    rest.canned_responses = [
        # Response for GET /api/v3/account/settings
        {
            "code": "00000",
            "msg": "success",
            "data": {"holdMode": "hedge_mode"},
        },
        # Response for POST /api/v3/trade/place-order
        {
            "code": "00000",
            "msg": "success",
            "data": {"orderId": "ord-buy-1"},
        },
        # Response for GET /api/v3/trade/order-info
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "orderId": "ord-buy-1",
                "symbol": "BTCUSDT",
                "side": "buy",
                "orderType": "market",
                "status": "live",
                "size": "0.01",
                "baseVolume": "0.0",
                "cTime": "1700000000000",
                "uTime": "1700000000000",
            },
        },
    ]
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())
    order = await client.create_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
    )
    assert order.order_id == "ord-buy-1"
    assert rest.last_data is not None
    assert rest.last_data["side"] == "buy"
    assert rest.last_data["posSide"] == "long"
    assert "reduceOnly" not in rest.last_data

    # Now test sell order (cached hold mode = hedge_mode)
    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": {"orderId": "ord-sell-1"},
        },
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "orderId": "ord-sell-1",
                "symbol": "BTCUSDT",
                "side": "sell",
                "orderType": "market",
                "status": "live",
                "size": "0.01",
                "baseVolume": "0.0",
                "cTime": "1700000000000",
                "uTime": "1700000000000",
            },
        },
    ]
    order_sell = await client.create_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
    )
    assert order_sell.order_id == "ord-sell-1"
    assert rest.last_data is not None
    assert rest.last_data["side"] == "sell"
    assert rest.last_data["posSide"] == "short"


@pytest.mark.asyncio
async def test_bitget_futures_create_order_one_way_mode() -> None:
    """Verify create_order in one_way_mode omits posSide and uses reduceOnly."""
    rest = MockBitgetRestClient()
    rest.canned_responses = [
        # Response for GET /api/v3/account/settings
        {
            "code": "00000",
            "msg": "success",
            "data": {"holdMode": "one_way_mode"},
        },
        # Response for POST /api/v3/trade/place-order
        {
            "code": "00000",
            "msg": "success",
            "data": {"orderId": "ord-reduce-1"},
        },
        # Response for GET /api/v3/trade/order-info
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "orderId": "ord-reduce-1",
                "symbol": "BTCUSDT",
                "side": "sell",
                "orderType": "market",
                "status": "live",
                "size": "0.01",
                "baseVolume": "0.0",
                "cTime": "1700000000000",
                "uTime": "1700000000000",
            },
        },
    ]
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())
    order = await client.create_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        reduce_only=True,
    )
    assert order.order_id == "ord-reduce-1"
    assert rest.last_data is not None
    assert rest.last_data["side"] == "sell"
    assert rest.last_data["reduceOnly"] == "YES"


def test_bitget_mapper_strategy_order() -> None:
    """Verify map_order properly maps TPSL plan orders without side but with posSide."""
    mapper = BitgetExchangeMapper()
    raw_sl = {
        "orderId": "1485899132632014849",
        "clientOid": "bsl-test-1",
        "symbol": "SHIBUSDT",
        "category": "USDT-FUTURES",
        "qty": "4370000",
        "posSide": "long",
        "stopLoss": "0.000005684",
        "type": "tpsl",
        "status": "pending",
        "createdTime": "1789991880567",
        "updatedTime": "1789991880585",
    }
    order = mapper.map_order(raw_sl)
    assert order.order_id == "1485899132632014849"
    assert order.client_order_id == "bsl-test-1"
    assert order.symbol == "SHIBUSDT"
    assert order.side is OrderSide.SELL
    assert order.order_type is OrderType.STOP_MARKET
    assert order.status is OrderStatus.NEW
    assert order.stop_price == Decimal("0.000005684")
    assert order.quantity == Decimal("4370000")

    raw_tp = {
        "orderId": "1485899132632014850",
        "clientOid": "btp-test-1",
        "symbol": "SHIBUSDT",
        "category": "USDT-FUTURES",
        "qty": "4370000",
        "posSide": "short",
        "takeProfit": "0.000005500",
        "type": "tpsl",
        "status": "pending",
        "createdTime": "1789991880567",
        "updatedTime": "1789991880585",
    }
    tp_order = mapper.map_order(raw_tp)
    assert tp_order.side is OrderSide.BUY
    assert tp_order.order_type is OrderType.TAKE_PROFIT_MARKET
    assert tp_order.stop_price == Decimal("0.000005500")


def test_bitget_mapper_order_status_fields() -> None:
    """Verify map_order maps orderStatus field from Bitget order-info."""
    mapper = BitgetExchangeMapper()
    raw = {
        "orderId": "1485899111776612353",
        "clientOid": "btg-test-order",
        "symbol": "SHIBUSDT",
        "orderType": "market",
        "side": "buy",
        "qty": "4370000",
        "cumExecQty": "4370000",
        "orderStatus": "filled",
    }
    order = mapper.map_order(raw)
    assert order.status is OrderStatus.FILLED
    assert order.executed_quantity == Decimal("4370000")

    raw_exec = {
        "orderId": "1485899111776612354",
        "symbol": "SHIBUSDT",
        "side": "buy",
        "orderType": "market",
        "orderStatus": "executed",
    }
    assert mapper.map_order(raw_exec).status is OrderStatus.FILLED


def test_bitget_mapper_trade_fills_payload() -> None:
    """Verify map_trade correctly extracts execPrice, execQty, feeDetail, execPnl."""
    mapper = BitgetExchangeMapper()
    raw_fill = {
        "execId": "1485904825235017728",
        "orderId": "1485904825228161024",
        "clientOid": "1485904825228161025",
        "symbol": "SHIBUSDT",
        "side": "sell",
        "tradeSide": "close_long",
        "execPrice": "0.000005741",
        "execQty": "4370000",
        "feeDetail": [{"feeCoin": "USDT", "fee": "0.0150529"}],
        "createdTime": "1789993237789",
        "execPnl": "0.11799",
    }
    trade = mapper.map_trade(raw_fill)
    assert trade.trade_id == "1485904825235017728"
    assert trade.order_id == "1485904825228161024"
    assert trade.symbol == "SHIBUSDT"
    assert trade.side is OrderSide.SELL
    assert trade.price == Decimal("0.000005741")
    assert trade.quantity == Decimal("4370000")
    assert trade.fee == Decimal("0.0150529")
    assert trade.fee_asset == "USDT"
    assert trade.realized_pnl == Decimal("0.11799")


@pytest.mark.asyncio
async def test_bitget_get_order_translates_not_found() -> None:
    """Verify get_order and get_order_by_client_order_id raise
    ExchangeOrderNotFoundError on 25204.
    """
    rest = MockBitgetRestClient()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    # Configure rest mock to raise BitgetRestResponseError
    async def fake_get(
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        del params, headers, authenticated
        raise BitgetRestResponseError(
            code="25204",
            message="Order does not exist",
            request_path=path,
            http_status=400,
        )

    setattr(rest, "get", fake_get)

    with pytest.raises(ExchangeOrderNotFoundError):
        await client.get_order(symbol="SHIBUSDT", order_id="999999")

    with pytest.raises(ExchangeOrderNotFoundError):
        await client.get_order_by_client_order_id(
            symbol="SHIBUSDT", client_order_id="eme-missing"
        )


# =============================================================================
# Regression Tests — protection order reconciliation (Bug 1, Bug 2)
# =============================================================================
def test_bitget_mapper_plan_order_pos_loss_maps_to_stop_market() -> None:
    """Regression: pos_loss planType must produce STOP_MARKET, not MARKET.

    Bitget V3 unfilled-strategy-orders returns planType='pos_loss' with
    orderType='market' (the post-trigger execution style).  Before the fix,
    the mapper used orderType and incorrectly produced OrderType.MARKET, which
    caused _validate_reconciled_leg_identity to raise RuntimeError.
    """
    mapper = BitgetExchangeMapper()
    payload = {
        "planOrderId": "strat-sl-001",
        "clientOid": "bsl-3e4e7c673b8343c6a52ca5167960c102",
        "symbol": "XRPUSDT",
        "posSide": "long",
        "orderType": "market",  # post-trigger execution type — NOT the trigger class
        "planType": "pos_loss",  # trigger class — determines SL vs TP
        "triggerPrice": "1.4778",
        "size": "16",
        "planStatus": "not_trigger",
        "cTime": "1700000000000",
        "uTime": "1700000000000",
    }
    order = mapper.map_order(payload)

    assert order.order_id == "strat-sl-001"
    assert order.client_order_id == "bsl-3e4e7c673b8343c6a52ca5167960c102"
    assert order.symbol == "XRPUSDT"
    assert order.side is OrderSide.SELL  # closing LONG → SELL
    assert order.order_type is OrderType.STOP_MARKET
    assert order.stop_price == Decimal("1.4778")
    assert order.quantity == Decimal("16")
    assert order.status is OrderStatus.NEW


def test_bitget_mapper_plan_order_pos_profit_maps_to_take_profit_market() -> None:
    """Regression: pos_profit planType must produce TAKE_PROFIT_MARKET, not MARKET."""
    mapper = BitgetExchangeMapper()
    payload = {
        "planOrderId": "strat-tp-001",
        "clientOid": "btp-068764063f8d462091100c9bb8531b25",
        "symbol": "XRPUSDT",
        "posSide": "long",
        "orderType": "market",
        "planType": "pos_profit",
        "triggerPrice": "1.5135",
        "size": "16",
        "planStatus": "not_trigger",
        "cTime": "1700000000000",
        "uTime": "1700000000000",
    }
    order = mapper.map_order(payload)

    assert order.order_id == "strat-tp-001"
    assert order.client_order_id == "btp-068764063f8d462091100c9bb8531b25"
    assert order.symbol == "XRPUSDT"
    assert order.side is OrderSide.SELL
    assert order.order_type is OrderType.TAKE_PROFIT_MARKET
    assert order.stop_price == Decimal("1.5135")
    assert order.quantity == Decimal("16")


def test_bitget_mapper_plan_order_zero_size_allowed() -> None:
    """Regression: plan order with size=0 (Bitget 'close all') must parse without error.

    When protection orders are placed without an explicit size, Bitget stores
    size='0'.  The mapper must not crash and must produce quantity=Decimal('0').
    The protection service's relaxed quantity check accepts 0 as 'close all'.
    """
    mapper = BitgetExchangeMapper()
    payload = {
        "planOrderId": "strat-sl-002",
        "clientOid": "bsl-abc",
        "symbol": "XRPUSDT",
        "posSide": "long",
        "orderType": "market",
        "planType": "pos_loss",
        "triggerPrice": "1.4778",
        "size": "0",
        "planStatus": "not_trigger",
        "cTime": "1700000000000",
        "uTime": "1700000000000",
    }
    order = mapper.map_order(payload)

    assert order.order_type is OrderType.STOP_MARKET
    assert order.stop_price == Decimal("1.4778")
    assert order.quantity == Decimal("0")


def test_bitget_mapper_plan_order_nested_stop_loss_dict() -> None:
    """Regression: nested stopLoss dict must extract triggerPrice as STOP_MARKET.

    Some Bitget V3 endpoints return stopLoss as an object:
        {"triggerPrice": "1.4778", "triggerType": "mark_price", "orderType": "market"}
    The mapper must extract the inner triggerPrice and classify as STOP_MARKET.
    """
    mapper = BitgetExchangeMapper()
    payload = {
        "planOrderId": "strat-sl-003",
        "clientOid": "bsl-nested",
        "symbol": "ETHUSDT",
        "posSide": "long",
        "orderType": "market",
        "planType": "",
        "stopLoss": {"triggerPrice": "2800.0", "triggerType": "mark_price"},
        "triggerPrice": "",
        "size": "1",
        "planStatus": "not_trigger",
        "cTime": "1700000000000",
        "uTime": "1700000000000",
    }
    order = mapper.map_order(payload)

    assert order.order_type is OrderType.STOP_MARKET
    assert order.stop_price == Decimal("2800.0")


def test_bitget_mapper_plan_order_nested_take_profit_dict() -> None:
    """Regression: nested takeProfit dict must produce TAKE_PROFIT_MARKET order type."""
    mapper = BitgetExchangeMapper()
    payload = {
        "planOrderId": "strat-tp-002",
        "clientOid": "btp-nested",
        "symbol": "ETHUSDT",
        "posSide": "long",
        "orderType": "market",
        "planType": "",
        "takeProfit": {"triggerPrice": "3200.0", "triggerType": "mark_price"},
        "triggerPrice": "",
        "size": "1",
        "planStatus": "not_trigger",
        "cTime": "1700000000000",
        "uTime": "1700000000000",
    }
    order = mapper.map_order(payload)

    assert order.order_type is OrderType.TAKE_PROFIT_MARKET
    assert order.stop_price == Decimal("3200.0")


@pytest.mark.asyncio
async def test_bitget_futures_create_protection_orders_atomic_combined_submission() -> (
    None
):
    """Regression: create_protection_orders submits combined TPSL in one atomic request.

    Submitting SL and TP in separate calls causes Bitget's position-level TPSL
    to overwrite the earlier leg. Both must be sent together with explicit size.
    """
    rest = MockBitgetRestClient()
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {"orderId": "strat-combined-1"},
    }
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    captured_data: dict[str, object] | None = None
    call_count = 0

    original_post = rest.post

    async def recording_post(
        path: str,
        *,
        params: QueryParams | None = None,
        data: dict[str, object] | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        nonlocal call_count, captured_data
        call_count += 1
        captured_data = data
        return await original_post(
            path,
            params=params,
            data=data,
            headers=headers,
            authenticated=authenticated,
        )

    rest.post = recording_post  # type: ignore[assignment]

    orders = await client.create_protection_orders(
        symbol="XRPUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("16"),
        stop_loss=Decimal("1.4778"),
        take_profit=Decimal("1.5135"),
        stop_loss_client_algo_id="bsl-test",
        take_profit_client_algo_id="btp-test",
    )

    assert call_count == 1, "Must submit both legs in a single atomic request"
    assert captured_data is not None
    assert captured_data.get("size") == "16"
    assert captured_data.get("stopLoss") == "1.4778"
    assert captured_data.get("takeProfit") == "1.5135"
    assert captured_data.get("type") == "tpsl"
    assert len(orders) == 2
    assert orders[0].order_type is OrderType.STOP_MARKET
    assert orders[0].stop_price == Decimal("1.4778")
    assert orders[0].client_order_id == "bsl-test"
    assert orders[1].order_type is OrderType.TAKE_PROFIT_MARKET
    assert orders[1].stop_price == Decimal("1.5135")
    assert orders[1].client_order_id == "btp-test"


def test_bitget_mapper_map_protection_orders_unpacks_combined_tpsl() -> None:
    """map_protection_orders unpacks combined SL+TP record into two distinct orders."""
    mapper = BitgetExchangeMapper()
    payload = {
        "planOrderId": "strat-combined-001",
        "clientOid": "bsl-3e4e7c673b8343c6a52ca5167960c102",
        "symbol": "XRPUSDT",
        "posSide": "long",
        "orderType": "market",
        "stopLoss": "1.4778",
        "takeProfit": "1.5135",
        "size": "16",
        "planStatus": "not_trigger",
        "cTime": "1700000000000",
        "uTime": "1700000000000",
    }
    orders = mapper.map_protection_orders(payload)

    assert len(orders) == 2
    sl, tp = orders

    assert sl.order_type is OrderType.STOP_MARKET
    assert sl.stop_price == Decimal("1.4778")
    assert sl.client_order_id == "bsl-3e4e7c673b8343c6a52ca5167960c102"
    assert sl.side is OrderSide.SELL
    assert sl.quantity == Decimal("16")

    assert tp.order_type is OrderType.TAKE_PROFIT_MARKET
    assert tp.stop_price == Decimal("1.5135")
    assert tp.client_order_id is None, "TP leg must not adopt bsl- client ID"
    assert tp.side is OrderSide.SELL
    assert tp.quantity == Decimal("16")


def test_bitget_mapper_map_order_tp_clears_bsl_client_id() -> None:
    """map_order must not return an SL client_order_id on a pure TP order."""
    mapper = BitgetExchangeMapper()
    payload = {
        "planOrderId": "strat-tp-only",
        "clientOid": "bsl-should-not-attach-to-tp",
        "symbol": "XRPUSDT",
        "posSide": "long",
        "orderType": "market",
        "takeProfit": "1.5135",
        "size": "16",
        "planStatus": "not_trigger",
        "cTime": "1700000000000",
        "uTime": "1700000000000",
    }
    order = mapper.map_order(payload)

    assert order.order_type is OrderType.TAKE_PROFIT_MARKET
    assert order.stop_price == Decimal("1.5135")
    assert order.client_order_id is None


@pytest.mark.asyncio
async def test_bitget_verify_mainnet_symbol_readiness_hedge_mode() -> None:
    """verify_mainnet_symbol_readiness sets leverage for long and short."""
    rest = MockBitgetRestClient()
    mapper = BitgetExchangeMapper()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=mapper)

    # 1. Contracts endpoint response
    contracts_response: JsonResponse = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "BTCUSDT",
                "maxLever": "125",
                "minTradeNum": "0.001",
                "maxOrderQty": "1000",
                "sizeMultiplier": "0.001",
                "pricePlace": "1",
                "minTradeUSDT": "5",
            }
        ],
    }
    # 2. Account settings response (hedge_mode)
    settings_response: JsonResponse = {
        "code": "00000",
        "msg": "success",
        "data": {"holdMode": "hedge_mode"},
    }
    # 3. set_leverage long
    lev_long_response: JsonResponse = {"code": "00000", "msg": "success", "data": {}}
    # 4. set_leverage short
    lev_short_response: JsonResponse = {"code": "00000", "msg": "success", "data": {}}

    rest.canned_responses = [
        contracts_response,
        settings_response,
        lev_long_response,
        lev_short_response,
    ]

    await client.verify_mainnet_symbol_readiness(
        symbol="btcusdt",
        maximum_leverage=3,
        entry_notional=Decimal("50"),
    )

    set_leverage_calls = [
        entry
        for entry in rest.history
        if entry == ("POST", "/api/v3/account/set-leverage")
    ]
    assert len(set_leverage_calls) == 2


@pytest.mark.asyncio
async def test_bitget_verify_mainnet_symbol_readiness_caps_at_max_leverage() -> None:
    """verify_mainnet_symbol_readiness caps leverage at symbol maxLever."""
    rest = MockBitgetRestClient()
    mapper = BitgetExchangeMapper()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=mapper)

    # 1. Contracts endpoint response with maxLever = 2
    contracts_response: JsonResponse = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "LOWLEVUSDT",
                "maxLever": "2",
                "minTradeNum": "1",
                "maxOrderQty": "1000",
                "sizeMultiplier": "1",
                "pricePlace": "2",
            }
        ],
    }
    # 2. Account settings response (one_way_mode)
    settings_response: JsonResponse = {
        "code": "00000",
        "msg": "success",
        "data": {"holdMode": "one_way_mode"},
    }
    lev_response: JsonResponse = {"code": "00000", "msg": "success", "data": {}}

    rest.canned_responses = [
        contracts_response,
        settings_response,
        lev_response,
    ]

    await client.verify_mainnet_symbol_readiness(
        symbol="LOWLEVUSDT",
        maximum_leverage=8,
        entry_notional=Decimal("50"),
    )

    assert rest.last_path == "/api/v3/account/set-leverage"
    assert rest.last_data == {
        "category": "USDT-FUTURES",
        "symbol": "LOWLEVUSDT",
        "leverage": "2",
        "posSide": "long",
        "marginMode": "crossed",
    }


@pytest.mark.asyncio
async def test_bitget_verify_mainnet_symbol_readiness_invalid_leverage() -> None:
    """verify_mainnet_symbol_readiness raises ValueError for invalid leverage."""
    rest = MockBitgetRestClient()
    mapper = BitgetExchangeMapper()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=mapper)

    with pytest.raises(ValueError, match="Maximum leverage must be greater than zero"):
        await client.verify_mainnet_symbol_readiness(
            symbol="BTCUSDT",
            maximum_leverage=0,
            entry_notional=Decimal("50"),
        )

    with pytest.raises(ValueError, match="Maximum leverage must be greater than zero"):
        # bool is an instance of int in Python, must fail validation
        await client.verify_mainnet_symbol_readiness(
            symbol="BTCUSDT",
            maximum_leverage=cast(int, True),
            entry_notional=Decimal("50"),
        )


@pytest.mark.asyncio
async def test_bitget_futures_exchange_client_adopted_protection_order() -> None:
    """Verify get_protection_order_by_client_id and cancel handle adopted- IDs."""
    rest = MockBitgetRestClient()
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "list": [
                {
                    "orderId": "1485957673526992966",
                    "clientOid": "bsl-123456",
                    "symbol": "BTCUSDT",
                    "planType": "pos_loss",
                    "triggerPrice": "50000",
                    "triggerType": "mark_price",
                    "status": "live",
                    "posMode": "one_way_mode",
                    "side": "buy",
                    "holdSide": "long",
                    "actualSize": "0.1",
                    "cTime": "1700000000000",
                    "uTime": "1700000000000",
                }
            ]
        },
    }
    mapper = BitgetExchangeMapper()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=mapper)

    # Lookup by adopted-{order_id}
    order = await client.get_protection_order_by_client_id(
        symbol="BTCUSDT",
        client_id="adopted-1485957673526992966",
    )
    assert order.order_id == "1485957673526992966"
    assert order.client_order_id == "adopted-1485957673526992966"

    # Cancel by adopted-{order_id}-tp strips suffix and sends orderId
    rest.canned_response = {"code": "00000", "msg": "success", "data": {}}
    await client.cancel_protection_order(
        symbol="BTCUSDT",
        client_id="adopted-1485957673526992966-tp",
    )
    assert rest.last_path == "/api/v3/trade/cancel-strategy-order"
    assert rest.last_data == {
        "category": "USDT-FUTURES",
        "symbol": "BTCUSDT",
        "orderId": "1485957673526992966",
    }


@pytest.mark.asyncio
async def test_bitget_get_account_ratio_success_and_period_normalization() -> None:
    """Verify get_account_ratio normalizes period and maps long/short ratios."""
    rest = MockBitgetRestClient()
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "longAccountRatio": "0.5500",
                "shortAccountRatio": "0.4500",
                "longShortAccountRatio": "1.2222",
                "ts": "1700000900000",
            },
            {
                "longAccountRatio": "0.6000",
                "shortAccountRatio": "0.4000",
                "longShortAccountRatio": "1.5000",
                "ts": "1700001800000",
            },
        ],
    }
    mapper = BitgetExchangeMapper()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=mapper)

    # Calling with '15min' normalizes to '15m'
    ratios = await client.get_account_ratio(
        symbol="BTCUSDT",
        period="15min",
        limit=10,
    )
    assert rest.last_path == "/api/v2/mix/market/account-long-short"
    assert rest.last_params == {
        "symbol": "BTCUSDT",
        "productType": "USDT-FUTURES",
        "period": "15m",
    }
    assert len(ratios) == 2
    ts1, buy1, sell1 = ratios[0]
    assert buy1 == Decimal("0.5500")
    assert sell1 == Decimal("0.4500")
    assert ts1.timestamp() == 1700000900.0

    ts2, buy2, sell2 = ratios[1]
    assert buy2 == Decimal("0.6000")
    assert sell2 == Decimal("0.4000")
    assert ts2.timestamp() == 1700001800.0

    # Test limit <= 0 returns empty
    empty = await client.get_account_ratio(symbol="BTCUSDT", limit=0)
    assert empty == ()


@pytest.mark.asyncio
async def test_bitget_open_interest_rolling_history() -> None:
    """Verify get_open_interest accumulates historical points across polls."""
    rest = MockBitgetRestClient()
    mapper = BitgetExchangeMapper()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=mapper)

    # First poll at t=1000
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "openInterestList": [{"symbol": "BTCUSDT", "size": "100.5"}],
            "ts": "1700001000000",
        },
    }
    points1 = await client.get_open_interest(symbol="BTCUSDT")
    assert len(points1) == 1
    assert points1[0][1] == Decimal("100.5")

    # Second poll at t=2000
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "openInterestList": [{"symbol": "BTCUSDT", "size": "105.0"}],
            "ts": "1700002000000",
        },
    }
    points2 = await client.get_open_interest(symbol="BTCUSDT")
    assert len(points2) == 2
    assert points2[0][1] == Decimal("100.5")
    assert points2[1][1] == Decimal("105.0")


def test_bitget_map_ticker_funding_rate_fallback() -> None:
    """Verify map_ticker reads fundingRate and falls back to fundRate."""
    mapper = BitgetExchangeMapper()

    ticker1 = mapper.map_ticker(
        {
            "symbol": "BTCUSDT",
            "lastPr": "50000",
            "ts": "1700000000000",
            "fundingRate": "0.0001",
        }
    )
    assert ticker1.funding_rate == Decimal("0.0001")

    ticker2 = mapper.map_ticker(
        {
            "symbol": "BTCUSDT",
            "lastPr": "50000",
            "ts": "1700000000000",
            "fundingRate": "",
            "fundRate": "-0.0002",
        }
    )
    assert ticker2.funding_rate == Decimal("-0.0002")


@pytest.mark.asyncio
async def test_bitget_get_protection_order_history() -> None:
    """Verify get_protection_order_history fetches and maps Bitget strategy orders."""
    rest = MockBitgetRestClient()
    mapper = BitgetExchangeMapper()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=mapper)

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "list": [
                {
                    "orderId": "plan-12345",
                    "clientOid": "bsl-00000000000000000000000000000001",
                    "symbol": "ETHUSDT",
                    "side": "sell",
                    "planType": "pos_loss",
                    "triggerPrice": "2400.0",
                    "size": "0.05",
                    "status": "executed",
                    "cTime": "1700000000000",
                    "uTime": "1700000001000",
                }
            ]
        },
    }

    start = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    end = datetime(2023, 11, 15, 22, 13, 20, tzinfo=UTC)
    orders = await client.get_protection_order_history(
        symbol="ETHUSDT",
        start_time=start,
        end_time=end,
    )

    assert len(orders) == 1
    assert orders[0].order_id == "plan-12345"
    assert orders[0].client_order_id == "bsl-00000000000000000000000000000001"
    assert orders[0].symbol == "ETHUSDT"
    assert orders[0].side is OrderSide.SELL
    assert orders[0].order_type is OrderType.STOP_MARKET
    assert orders[0].status is OrderStatus.FILLED
    assert orders[0].stop_price == Decimal("2400.0")

    assert rest.last_path == "/api/v3/trade/history-strategy-orders"
    assert rest.last_params == {
        "category": "USDT-FUTURES",
        "symbol": "ETHUSDT",
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000),
        "limit": 100,
    }


@pytest.mark.asyncio
async def test_bitget_base_client_get_protection_order_history_raises() -> None:
    """Verify base BitgetClient raises NotImplementedError for history."""
    rest = MockBitgetRestClient()
    mapper = BitgetExchangeMapper()
    base_client = BitgetClient(rest=rest, mapper=mapper)

    with pytest.raises(NotImplementedError, match="must be implemented by subclass"):
        await base_client.get_protection_order_history(
            symbol="BTCUSDT",
            start_time=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_bitget_get_protection_order_resolves_companion_tpsl_leg() -> None:
    """Verify get_protection_order_by_client_id correlates unmapped companion leg."""
    rest = MockBitgetRestClient()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "orderId": "1486065050578296872",
                "clientOid": "bsl-23a2d6561dac4c83851a5489dc0d5a2a",
                "symbol": "ARXUSDT",
                "category": "USDT-FUTURES",
                "qty": "124",
                "posSide": "short",
                "takeProfit": "0.19777",
                "stopLoss": "0.20326",
                "type": "tpsl",
                "status": "pending",
            }
        ],
    }

    # SL leg matches direct clientOid
    sl_order = await client.get_protection_order_by_client_id(
        symbol="ARXUSDT",
        client_id="bsl-23a2d6561dac4c83851a5489dc0d5a2a",
    )
    assert sl_order.order_id == "1486065050578296872-sl"
    assert sl_order.client_order_id == "bsl-23a2d6561dac4c83851a5489dc0d5a2a"
    assert sl_order.order_type is OrderType.STOP_MARKET
    assert sl_order.stop_price == Decimal("0.20326")

    # TP leg was stored without clientOid on Bitget; client resolves it cleanly
    tp_order = await client.get_protection_order_by_client_id(
        symbol="ARXUSDT",
        client_id="btp-d0dcc18f04434cb59945dd3e50908213",
    )
    assert tp_order.order_id == "1486065050578296872-tp"
    assert tp_order.client_order_id == "btp-d0dcc18f04434cb59945dd3e50908213"
    assert tp_order.order_type is OrderType.TAKE_PROFIT_MARKET
    assert tp_order.stop_price == Decimal("0.19777")


@pytest.mark.asyncio
async def test_bitget_cancel_protection_order_companion_leg_uses_order_id() -> None:
    """Verify cancel_protection_order sends orderId when cancelling companion leg."""
    rest = MockBitgetRestClient()
    client = BitgetFuturesExchangeClient(rest=rest, mapper=BitgetExchangeMapper())

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "orderId": "1486065050578296872",
                "clientOid": "bsl-23a2d6561dac4c83851a5489dc0d5a2a",
                "symbol": "ARXUSDT",
                "category": "USDT-FUTURES",
                "qty": "124",
                "posSide": "short",
                "takeProfit": "0.19777",
                "stopLoss": "0.20326",
                "type": "tpsl",
                "status": "pending",
            }
        ],
    }

    await client.cancel_protection_order(
        symbol="ARXUSDT",
        client_id="btp-d0dcc18f04434cb59945dd3e50908213",
    )

    assert rest.last_path == "/api/v3/trade/cancel-strategy-order"
    assert rest.last_data == {
        "category": "USDT-FUTURES",
        "symbol": "ARXUSDT",
        "orderId": "1486065050578296872",
    }
