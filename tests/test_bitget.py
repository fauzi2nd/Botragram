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
from datetime import datetime, timezone
from decimal import Decimal

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
from botragram.exceptions import ExchangeError
from botragram.exchanges.base.rest import (
    JsonResponse,
    QueryParams,
    RequestHeaders,
)
from botragram.exchanges.bitget.futures_client import BitgetFuturesExchangeClient
from botragram.exchanges.bitget.mapper import BitgetExchangeMapper
from botragram.exchanges.bitget.rest import BitgetRestClient
from botragram.exchanges.bitget.stream import BitgetStreamClient
from botragram.exchanges.factory import ExchangeFactory


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
