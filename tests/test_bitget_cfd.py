"""
Botragram

Description:
    Unit and contract tests for Bitget CFD client, mapper, and factory wiring.

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
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine import (
    CfdFinancingEngine,
    CfdSizingEngine,
    MarketCalendarEngine,
)
from botragram.enums import (
    AssetClass,
    ExchangeType,
    Interval,
    MarketSessionStatus,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.exceptions import (
    ExchangeError,
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.base.rest import JsonResponse, QueryParams, RequestHeaders
from botragram.exchanges.bitget import (
    BitgetCfdExchangeClient,
    BitgetCfdMapper,
    BitgetRestClient,
)
from botragram.exchanges.bitget.rest import BitgetRestResponseError
from botragram.exchanges.factory import ExchangeFactory
from botragram.models import (
    CfdContractSpec,
    CfdFinancingSchedule,
    CfdMarginRequirement,
    CfdOvernightSwapEstimate,
    MarketSession,
    PipCalculationResult,
    Position,
)


# =============================================================================
# Mock REST Client
# =============================================================================
class MockBitgetRestClient(BitgetRestClient):
    """Mock REST transport returning predefined responses."""

    def __init__(self) -> None:
        super().__init__(
            base_url="https://api.bitget.com",
            api_key="mock-key",
            api_secret="mock-secret",
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

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

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
            return self._validate_response_envelope(self.canned_responses.pop(0))
        return self._validate_response_envelope(self.canned_response)

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: dict[str, object] | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = True,
    ) -> JsonResponse:
        del headers, authenticated
        self.history.append(("POST", path))
        self.last_method = "POST"
        self.last_path = path
        self.last_params = params
        self.last_data = data
        if self.canned_responses:
            return self._validate_response_envelope(self.canned_responses.pop(0))
        return self._validate_response_envelope(self.canned_response)


# =============================================================================
# Mapper Tests
# =============================================================================
def test_cfd_mapper_normalize_and_vendor_symbol() -> None:
    """Test symbol normalization and suffix additions."""
    mapper = BitgetCfdMapper()

    # Normalization
    assert mapper.normalize_symbol("XAUUSD.s") == "XAUUSD"
    assert mapper.normalize_symbol("EURUSD.pro") == "EURUSD"
    assert mapper.normalize_symbol("BTCUSD") == "BTCUSD"

    # Vendor symbol conversion
    assert mapper.to_vendor_symbol("XAUUSD", mode="zero_fee") == "XAUUSD.s"
    assert mapper.to_vendor_symbol("EURUSD", mode="pro") == "EURUSD.pro"
    assert mapper.to_vendor_symbol("US100", mode="ecn") == "US100"


def test_cfd_mapper_map_ticker() -> None:
    """Test mapping CFD ticker payload into domain Ticker model."""
    mapper = BitgetCfdMapper()
    payload = {
        "symbol": "XAUUSD.s",
        "lastPr": "2650.50",
        "bidPr": "2650.40",
        "askPr": "2650.60",
        "ts": "1700000000000",
    }
    ticker = mapper.map_ticker(payload)
    assert ticker.symbol == "XAUUSD"
    assert ticker.last_price == Decimal("2650.50")
    assert ticker.bid_price == Decimal("2650.40")
    assert ticker.ask_price == Decimal("2650.60")
    assert ticker.timestamp == datetime.fromtimestamp(1700000000, tz=UTC)
    assert ticker.funding_rate is None


def test_cfd_mapper_map_candle() -> None:
    """Test mapping CFD candlestick tuple into Candle model."""
    mapper = BitgetCfdMapper()
    row = (
        "1700000000000",
        "2650.00",
        "2655.00",
        "2648.00",
        "2653.00",
        "1500.5",
    )
    candle = mapper.map_candle(row, symbol="XAUUSD.s", interval=Interval.M5)
    assert candle.symbol == "XAUUSD"
    assert candle.interval == Interval.M5
    assert candle.open_price == Decimal("2650.00")
    assert candle.high_price == Decimal("2655.00")
    assert candle.low_price == Decimal("2648.00")
    assert candle.close_price == Decimal("2653.00")
    assert candle.volume == Decimal("1500.5")


def test_cfd_mapper_map_account() -> None:
    """Test mapping CFD account fund details into Account model."""
    mapper = BitgetCfdMapper()
    payload = {
        "marginCoin": "USDT",
        "equity": "10000.00",
        "available": "8000.00",
        "ts": "1700000000000",
    }
    account = mapper.map_account(payload)
    assert len(account.balances) == 1
    assert account.balances[0].asset == "USDT"
    assert account.balances[0].free == Decimal("8000.00")
    assert account.balances[0].locked == Decimal("2000.00")
    assert account.can_trade is True


def test_cfd_mapper_map_order() -> None:
    """Test mapping CFD order payload into Order model."""
    mapper = BitgetCfdMapper()
    payload = {
        "orderId": "cfd_ord_123",
        "clientOid": "client_123",
        "symbol": "EURUSD.s",
        "side": "BUY",
        "orderType": "LIMIT",
        "status": "FILLED",
        "price": "1.0850",
        "size": "1.0",
        "filledQty": "1.0",
        "cTime": "1700000000000",
    }
    order = mapper.map_order(payload)
    assert order.order_id == "cfd_ord_123"
    assert order.client_order_id == "client_123"
    assert order.symbol == "EURUSD"
    assert order.side == OrderSide.BUY
    assert order.order_type == OrderType.LIMIT
    assert order.status == OrderStatus.FILLED
    assert order.price == Decimal("1.0850")
    assert order.quantity == Decimal("1.0")
    assert order.executed_quantity == Decimal("1.0")


def test_cfd_mapper_map_position() -> None:
    """Test mapping CFD position payload into Position model."""
    mapper = BitgetCfdMapper()
    payload = {
        "symbol": "XAUUSD",
        "posSide": "LONG",
        "total": "2.5",
        "openPriceAvg": "2600.00",
        "markPrice": "2650.00",
        "unrealizedPl": "125.00",
        "margin": "500.00",
        "leverage": "50",
        "uTime": "1700000000000",
        "positionId": "pos-cfd-12345",
    }
    position = mapper.map_position(payload)
    assert position.symbol == "XAUUSD"
    assert position.side == PositionSide.LONG
    assert position.quantity == Decimal("2.5")
    assert position.entry_price == Decimal("2600.00")
    assert position.current_price == Decimal("2650.00")
    assert position.unrealized_pnl == Decimal("125.00")
    assert position.leverage == 50
    assert position.position_id == "pos-cfd-12345"


# =============================================================================
# Client Tests
# =============================================================================
@pytest.mark.asyncio
async def test_cfd_client_contract_conformance() -> None:
    """Verify BitgetCfdExchangeClient conforms to BaseExchangeClient interface."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="zero_fee")

    assert isinstance(client, BaseExchangeClient)
    assert client.mode == "zero_fee"

    await client.connect()
    await client.close()


@pytest.mark.asyncio
async def test_cfd_client_get_ticker() -> None:
    """Verify get_ticker queries CFD tickers endpoint."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="zero_fee")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "XAUUSD.s",
                "lastPr": "2650.00",
                "bidPr": "2649.50",
                "askPr": "2650.50",
                "ts": "1700000000000",
            }
        ],
    }

    ticker = await client.get_ticker(symbol="XAUUSD")
    assert ticker.symbol == "XAUUSD"
    assert ticker.last_price == Decimal("2650.00")
    assert rest.last_path == "/api/v3/cfd/market/tickers"
    assert rest.last_params == {"symbol": "XAUUSD.s"}


@pytest.mark.asyncio
async def test_cfd_client_create_and_cancel_order() -> None:
    """Verify create_order and cancel_order send requests to CFD endpoints."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "orderId": "order_cfd_99",
            "clientOid": "cl_99",
            "symbol": "EURUSD",
            "side": "buy",
            "orderType": "market",
            "status": "new",
            "size": "0.1",
            "cTime": "1700000000000",
        },
    }

    order = await client.create_order(
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
        client_order_id="cl_99",
    )
    assert order.order_id == "order_cfd_99"
    assert rest.last_path == "/api/v3/cfd/trade/place-order"
    assert rest.last_data is not None
    assert rest.last_data["symbol"] == "EURUSD"
    assert rest.last_data["side"] == "buy"

    # Cancel order
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "orderId": "order_cfd_99",
            "symbol": "EURUSD",
            "status": "canceled",
            "cTime": "1700000000000",
        },
    }
    canceled = await client.cancel_order(symbol="EURUSD", order_id="order_cfd_99")
    assert canceled.status == OrderStatus.CANCELED
    assert rest.last_path == "/api/v3/cfd/trade/cancel-order"


@pytest.mark.asyncio
async def test_cfd_client_get_positions() -> None:
    """Verify get_positions retrieves open CFD positions."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "XAUUSD",
                "posSide": "long",
                "total": "1.0",
                "openPriceAvg": "2600.0",
                "markPrice": "2610.0",
                "unrealizedPl": "10.0",
                "margin": "50.0",
                "leverage": "50",
                "uTime": "1700000000000",
            }
        ],
    }

    positions = await client.get_positions(symbol="XAUUSD")
    assert len(positions) == 1
    assert positions[0].symbol == "XAUUSD"
    assert positions[0].side == PositionSide.LONG
    assert rest.last_path == "/api/v3/cfd/trade/current-positions"


@pytest.mark.asyncio
async def test_cfd_client_create_order_uses_qty_payload() -> None:
    """Verify create_order submits 'qty' rather than 'size' per Bitget CFD contract."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "orderId": "order_cfd_001",
            "clientOid": "client_order_001",
            "symbol": "XAUUSD",
            "side": "buy",
            "orderType": "market",
            "status": "new",
            "qty": "0.15",
            "cTime": "1700000000000",
        },
    }

    order = await client.create_order(
        symbol="XAUUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.15"),
        client_order_id="client_order_001",
        bypass_calendar_guard=True,
    )

    assert order.order_id == "order_cfd_001"
    assert rest.last_path == "/api/v3/cfd/trade/place-order"
    assert rest.last_data is not None
    assert rest.last_data["qty"] == "0.15"
    assert "size" not in rest.last_data


@pytest.mark.asyncio
async def test_cfd_client_close_position_resolves_position_id() -> None:
    """Verify close_position automatically resolves positionId and qty."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    # First call: get_positions
    # Second call: close-positions
    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "symbol": "XAUUSD",
                    "posSide": "long",
                    "positionId": "pos-cfd-resolved-789",
                    "total": "0.25",
                    "openPriceAvg": "2600.0",
                    "markPrice": "2610.0",
                    "unrealizedPl": "25.0",
                    "leverage": "50",
                    "uTime": "1700000000000",
                }
            ],
        },
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "orderId": "close_order_999",
                "clientOid": "close_client_999",
                "symbol": "XAUUSD",
                "side": "sell",
                "orderType": "market",
                "status": "closed",
                "qty": "0.25",
                "cTime": "1700000000000",
            },
        },
    ]

    closed = await client.close_position(
        symbol="XAUUSD",
        client_order_id="close_client_999",
        bypass_calendar_guard=True,
    )

    assert closed.order_id == "close_order_999"
    assert rest.last_path == "/api/v3/cfd/trade/close-positions"
    assert rest.last_data is not None
    assert rest.last_data["positionId"] == "pos-cfd-resolved-789"
    assert rest.last_data["qty"] == "0.25"
    assert rest.last_data["clientOid"] == "close_client_999"


# =============================================================================
# Factory Tests
# =============================================================================
def test_exchange_factory_bitget_cfd() -> None:
    """Verify factory instantiates BitgetCfdExchangeClient for MarketType.CFD."""
    rest = MockBitgetRestClient()
    client = ExchangeFactory.create_exchange_client(
        exchange_type=ExchangeType.BITGET,
        rest_client=rest,
        market_type=MarketType.CFD,
    )
    assert isinstance(client, BitgetCfdExchangeClient)


def test_exchange_factory_bitget_unsupported_market() -> None:
    """Verify ExchangeFactory rejects unsupported market types for Bitget."""
    rest = MockBitgetRestClient()
    with pytest.raises(ValueError, match="supports FUTURES and CFD"):
        ExchangeFactory.create_exchange_client(
            exchange_type=ExchangeType.BITGET,
            rest_client=rest,
            market_type=MarketType.SPOT,
        )


# =============================================================================
# Protection Orders Tests (Phase 1)
# =============================================================================
def test_cfd_mapper_map_protection_orders_unpacks_combined_tpsl() -> None:
    """Verify combined TPSL strategy payload is unpacked into two distinct orders."""
    mapper = BitgetCfdMapper()
    payload = {
        "orderId": "plan_999",
        "clientOid": "bsl-algo-1",
        "symbol": "XAUUSD.s",
        "side": "SELL",
        "orderType": "PLAN",
        "status": "NEW",
        "stopLoss": "2600.00",
        "takeProfit": "2700.00",
        "size": "1.0",
        "cTime": "1700000000000",
    }
    orders = mapper.map_protection_orders(payload)
    assert len(orders) == 2
    sl_order, tp_order = orders[0], orders[1]

    assert sl_order.order_id == "plan_999-sl"
    assert sl_order.order_type == OrderType.STOP_MARKET
    assert sl_order.stop_price == Decimal("2600.00")
    assert sl_order.client_order_id == "bsl-algo-1"

    assert tp_order.order_id == "plan_999-tp"
    assert tp_order.order_type == OrderType.TAKE_PROFIT_MARKET
    assert tp_order.stop_price == Decimal("2700.00")
    assert tp_order.client_order_id is None


@pytest.mark.asyncio
async def test_cfd_client_create_combined_protection_orders() -> None:
    """Verify create_protection_orders submits atomic combined TPSL order."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="zero_fee")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {"orderId": "cfd_plan_001"},
    }

    orders = await client.create_protection_orders(
        symbol="XAUUSD",
        side=OrderSide.SELL,
        quantity=Decimal("1.5"),
        stop_loss=Decimal("2610.00"),
        take_profit=Decimal("2710.00"),
        stop_loss_client_algo_id="bsl-123",
        take_profit_client_algo_id="btp-456",
    )
    assert len(orders) == 2
    assert rest.last_path == "/api/v3/cfd/trade/place-strategy-order"
    assert rest.last_data is not None
    assert rest.last_data["symbol"] == "XAUUSD.s"
    assert rest.last_data["type"] == "tpsl"
    assert rest.last_data["stopLoss"] == "2610.00"
    assert rest.last_data["takeProfit"] == "2710.00"
    assert rest.last_data["size"] == "1.5"


@pytest.mark.asyncio
async def test_cfd_client_get_open_protection_orders() -> None:
    """Verify get_open_protection_orders queries unfilled strategy orders."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "orderId": "cfd_plan_002",
                "clientOid": "bsl-test-1",
                "symbol": "EURUSD",
                "side": "sell",
                "orderType": "PLAN",
                "status": "new",
                "stopLoss": "1.0750",
                "size": "0.5",
                "cTime": "1700000000000",
            }
        ],
    }

    orders = await client.get_open_protection_orders(symbol="EURUSD")
    assert len(orders) == 1
    assert orders[0].order_id == "cfd_plan_002"
    assert orders[0].stop_price == Decimal("1.0750")
    assert rest.last_path == "/api/v3/cfd/trade/unfilled-strategy-orders"


@pytest.mark.asyncio
async def test_cfd_client_ensure_stop_loss_order() -> None:
    """Verify ensure_stop_loss_order cancels previous SL and places new one."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {"orderId": "cfd_plan_new"},
    }

    order = await client.ensure_stop_loss_order(
        symbol="EURUSD",
        side=OrderSide.SELL,
        quantity=Decimal("0.5"),
        stop_loss=Decimal("1.0780"),
        client_algo_id="bsl-new",
        previous_client_algo_id="bsl-old",
    )
    assert order.stop_price == Decimal("1.0780")
    paths = [item[1] for item in rest.history]
    assert "/api/v3/cfd/trade/cancel-strategy-order" in paths
    assert "/api/v3/cfd/trade/place-strategy-order" in paths


@pytest.mark.asyncio
async def test_cfd_client_cancel_protection_order() -> None:
    """Verify cancel_protection_order routes to cancel strategy order endpoint."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {"code": "00000", "msg": "success", "data": {}}
    await client.cancel_protection_order(symbol="EURUSD", client_id="bsl-cancel")
    assert rest.last_path == "/api/v3/cfd/trade/cancel-strategy-order"
    assert rest.last_data is not None
    assert rest.last_data["clientOid"] == "bsl-cancel"


@pytest.mark.asyncio
async def test_cfd_client_get_protection_order_by_client_id() -> None:
    """Verify get_protection_order_by_client_id finds order or companion leg."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "orderId": "cfd_plan_combo",
                "clientOid": "bsl-combo-sl",
                "symbol": "XAUUSD",
                "side": "sell",
                "orderType": "tpsl",
                "status": "new",
                "stopLoss": "2600.00",
                "takeProfit": "2700.00",
                "size": "1.0",
                "cTime": "1700000000000",
            }
        ],
    }

    # Find companion take-profit leg
    tp_order = await client.get_protection_order_by_client_id(
        symbol="XAUUSD", client_id="btp-companion"
    )
    assert tp_order.order_type == OrderType.TAKE_PROFIT_MARKET
    assert tp_order.stop_price == Decimal("2700.00")
    assert tp_order.client_order_id == "btp-companion"

    # Unknown ID raises ExchangeOrderNotFoundError
    with pytest.raises(ExchangeOrderNotFoundError):
        await client.get_protection_order_by_client_id(
            symbol="XAUUSD", client_id="unknown-id"
        )


@pytest.mark.asyncio
async def test_cfd_create_protection_orders_tp_preserves_existing_venue_sl() -> None:
    """Verify CFD TP submission preserves active venue SL."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "orderId": "cfd_sl_venue",
                    "clientOid": "bsl-venue-sl",
                    "symbol": "XAUUSD",
                    "side": "sell",
                    "orderType": "tpsl",
                    "status": "new",
                    "stopLoss": "2600.00",
                    "size": "1.0",
                    "cTime": "1700000000000",
                }
            ],
        },
        {
            "code": "00000",
            "msg": "success",
            "data": {"orderId": "cfd_tp_created"},
        },
    ]

    orders = await client.create_protection_orders(
        symbol="XAUUSD",
        side=OrderSide.SELL,
        quantity=Decimal("1.0"),
        take_profit=Decimal("2700.00"),
        take_profit_client_algo_id="btp-unique-tp",
        bypass_calendar_guard=True,
    )

    assert len(orders) == 1
    assert orders[0].order_type is OrderType.TAKE_PROFIT_MARKET
    assert rest.last_path == "/api/v3/cfd/trade/place-strategy-order"
    assert rest.last_data is not None
    assert rest.last_data["stopLoss"] == "2600.00"
    assert rest.last_data["takeProfit"] == "2700.00"
    assert rest.last_data["clientOid"] == "btp-unique-tp"


@pytest.mark.asyncio
async def test_cfd_create_protection_orders_sl_preserves_existing_venue_tp() -> None:
    """Verify CFD SL submission preserves active venue TP."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "orderId": "cfd_tp_venue",
                    "clientOid": "btp-venue-tp",
                    "symbol": "XAUUSD",
                    "side": "sell",
                    "orderType": "tpsl",
                    "status": "new",
                    "takeProfit": "2700.00",
                    "size": "1.0",
                    "cTime": "1700000000000",
                }
            ],
        },
        {
            "code": "00000",
            "msg": "success",
            "data": {"orderId": "cfd_sl_created"},
        },
    ]

    orders = await client.create_protection_orders(
        symbol="XAUUSD",
        side=OrderSide.SELL,
        quantity=Decimal("1.0"),
        stop_loss=Decimal("2600.00"),
        stop_loss_client_algo_id="bsl-unique-sl",
        bypass_calendar_guard=True,
    )

    assert len(orders) == 1
    assert orders[0].order_type is OrderType.STOP_MARKET
    assert rest.last_path == "/api/v3/cfd/trade/place-strategy-order"
    assert rest.last_data is not None
    assert rest.last_data["stopLoss"] == "2600.00"
    assert rest.last_data["takeProfit"] == "2700.00"
    assert rest.last_data["clientOid"] == "bsl-unique-sl"


@pytest.mark.asyncio
async def test_cfd_create_protection_orders_sl_fails_closed_when_lookup_errors() -> (
    None
):
    """Fail closed when CFD opposite-leg lookup returns exchange error: ZERO POST."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_responses = [
        {
            "code": "40014",
            "msg": "Param error",
            "data": {},
        }
    ]

    with pytest.raises(BitgetRestResponseError):
        await client.create_protection_orders(
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=Decimal("1.0"),
            stop_loss=Decimal("2600.00"),
            stop_loss_client_algo_id="bsl-fail-sl",
            bypass_calendar_guard=True,
        )

    assert not any(method == "POST" for method, _ in rest.history)


@pytest.mark.asyncio
async def test_cfd_create_protection_orders_tp_fails_closed_when_lookup_errors() -> (
    None
):
    """Fail closed when CFD opposite-leg lookup returns exchange error: ZERO POST."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_responses = [
        {
            "code": "40014",
            "msg": "Param error",
            "data": {},
        }
    ]

    with pytest.raises(BitgetRestResponseError):
        await client.create_protection_orders(
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=Decimal("1.0"),
            take_profit=Decimal("2700.00"),
            take_profit_client_algo_id="btp-fail-tp",
            bypass_calendar_guard=True,
        )

    assert not any(method == "POST" for method, _ in rest.history)


@pytest.mark.asyncio
async def test_cfd_create_protection_orders_fails_closed_on_network_timeout() -> None:
    """Fail closed when CFD opposite-leg lookup times out: ZERO POST."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    async def _failing_get(*args: object, **kwargs: object) -> JsonResponse:
        del args, kwargs
        raise TimeoutError("Network timeout querying cfd open orders")

    rest.get = _failing_get  # type: ignore

    with pytest.raises(ExchangeError, match="Bitget CFD network failure"):
        await client.create_protection_orders(
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=Decimal("1.0"),
            stop_loss=Decimal("2600.00"),
            stop_loss_client_algo_id="bsl-timeout-sl",
            bypass_calendar_guard=True,
        )

    assert not any(method == "POST" for method, _ in rest.history)


@pytest.mark.asyncio
async def test_cfd_create_protection_orders_cancellation_propagates() -> None:
    """Cancellation during CFD opposite-leg lookup must propagate: ZERO POST."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    async def _cancelled_get(*args: object, **kwargs: object) -> JsonResponse:
        del args, kwargs
        raise asyncio.CancelledError()

    rest.get = _cancelled_get  # type: ignore

    with pytest.raises(asyncio.CancelledError):
        await client.create_protection_orders(
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=Decimal("1.0"),
            stop_loss=Decimal("2600.00"),
            stop_loss_client_algo_id="bsl-cancel-sl",
            bypass_calendar_guard=True,
        )

    assert not any(method == "POST" for method, _ in rest.history)


@pytest.mark.asyncio
async def test_cfd_create_protection_orders_sl_only_posts_when_no_opposite_leg() -> (
    None
):
    """When no opposite TP exists, CFD SL single-leg is posted without takeProfit."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": [],
        },
        {
            "code": "00000",
            "msg": "success",
            "data": {"orderId": "cfd_sl_solo"},
        },
    ]

    orders = await client.create_protection_orders(
        symbol="XAUUSD",
        side=OrderSide.SELL,
        quantity=Decimal("1.0"),
        stop_loss=Decimal("2600.00"),
        stop_loss_client_algo_id="bsl-cfd-solo-sl",
        bypass_calendar_guard=True,
    )

    assert len(orders) == 1
    assert orders[0].order_type is OrderType.STOP_MARKET
    assert orders[0].client_order_id == "bsl-cfd-solo-sl"
    assert rest.last_path == "/api/v3/cfd/trade/place-strategy-order"
    assert rest.last_data is not None
    assert rest.last_data["stopLoss"] == "2600.00"
    assert "takeProfit" not in rest.last_data
    assert rest.last_data["clientOid"] == "bsl-cfd-solo-sl"
    assert any(method == "POST" for method, _ in rest.history)


@pytest.mark.asyncio
async def test_cfd_create_protection_orders_tp_only_posts_when_no_opposite_leg() -> (
    None
):
    """When no opposite SL exists, CFD TP single-leg is posted without stopLoss."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": [],
        },
        {
            "code": "00000",
            "msg": "success",
            "data": {"orderId": "cfd_tp_solo"},
        },
    ]

    orders = await client.create_protection_orders(
        symbol="XAUUSD",
        side=OrderSide.SELL,
        quantity=Decimal("1.0"),
        take_profit=Decimal("2700.00"),
        take_profit_client_algo_id="btp-cfd-solo-tp",
        bypass_calendar_guard=True,
    )

    assert len(orders) == 1
    assert orders[0].order_type is OrderType.TAKE_PROFIT_MARKET
    assert orders[0].client_order_id == "btp-cfd-solo-tp"
    assert rest.last_path == "/api/v3/cfd/trade/place-strategy-order"
    assert rest.last_data is not None
    assert rest.last_data["takeProfit"] == "2700.00"
    assert "stopLoss" not in rest.last_data
    assert rest.last_data["clientOid"] == "btp-cfd-solo-tp"
    assert any(method == "POST" for method, _ in rest.history)


@pytest.mark.asyncio
async def test_cfd_create_protection_orders_fails_closed_when_outcome_unknown() -> None:
    """Fail closed when CFD opposite-leg lookup outcome is unknown: ZERO POST."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    async def _unknown_get(*args: object, **kwargs: object) -> JsonResponse:
        del args, kwargs
        raise ExchangeOrderOutcomeUnknownError("Outcome unknown querying CFD orders")

    rest.get = _unknown_get  # type: ignore

    with pytest.raises(ExchangeOrderOutcomeUnknownError):
        await client.create_protection_orders(
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=Decimal("1.0"),
            stop_loss=Decimal("2600.00"),
            stop_loss_client_algo_id="bsl-cfd-unknown-sl",
            bypass_calendar_guard=True,
        )

    assert not any(method == "POST" for method, _ in rest.history)


# =============================================================================
# Phase 2: Market Calendar and Trading Hours Guard Tests
# =============================================================================


def test_market_calendar_classify_asset() -> None:
    """Verify asset classification across TradFi and Crypto instruments."""
    calendar = MarketCalendarEngine()

    assert calendar.classify_asset("EURUSD") == AssetClass.FOREX
    assert calendar.classify_asset("EURUSD.s") == AssetClass.FOREX
    assert calendar.classify_asset("GBPUSD.pro") == AssetClass.FOREX
    assert calendar.classify_asset("USDJPY_ecn") == AssetClass.FOREX
    assert calendar.classify_asset("AUDCAD") == AssetClass.FOREX

    assert calendar.classify_asset("XAUUSD") == AssetClass.COMMODITY
    assert calendar.classify_asset("XAGUSD.s") == AssetClass.COMMODITY
    assert calendar.classify_asset("USOIL") == AssetClass.COMMODITY
    assert calendar.classify_asset("BRENT") == AssetClass.COMMODITY
    assert calendar.classify_asset("COCOA") == AssetClass.COMMODITY
    assert calendar.classify_asset("COFFEE") == AssetClass.COMMODITY
    assert calendar.classify_asset("COTTON") == AssetClass.COMMODITY
    assert calendar.classify_asset("UKOUSD") == AssetClass.COMMODITY
    assert calendar.classify_asset("USOUSD") == AssetClass.COMMODITY

    assert calendar.classify_asset("US30") == AssetClass.INDEX
    assert calendar.classify_asset("SPX500.s") == AssetClass.INDEX
    assert calendar.classify_asset("NAS100") == AssetClass.INDEX
    assert calendar.classify_asset("GER40") == AssetClass.INDEX
    assert calendar.classify_asset("DE40") == AssetClass.INDEX
    assert calendar.classify_asset("ESP35") == AssetClass.INDEX
    assert calendar.classify_asset("AUS200") == AssetClass.INDEX
    assert calendar.classify_asset("SPY") == AssetClass.INDEX

    assert calendar.classify_asset("BTCUSD.cfd") == AssetClass.CRYPTO
    assert calendar.classify_asset("ETHUSDT") == AssetClass.CRYPTO
    assert calendar.classify_asset("SOLUSD") == AssetClass.CRYPTO


def test_market_calendar_forex_hours() -> None:
    """Verify Forex trading schedule (Sunday 21:00 UTC - Friday 22:00 UTC)."""
    calendar = MarketCalendarEngine()

    # Tuesday 14:00 UTC -> Open
    tuesday_open = datetime(2026, 9, 22, 14, 0, tzinfo=timezone.utc)
    session = calendar.get_session("EURUSD", at=tuesday_open)
    assert session.is_open is True
    assert session.status == MarketSessionStatus.OPEN
    assert session.next_close == datetime(2026, 9, 25, 22, 0, tzinfo=timezone.utc)

    # Friday 21:00 UTC -> Open (approaching close at 22:00)
    friday_preclose = datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc)
    assert calendar.is_market_open("EURUSD", at=friday_preclose) is True

    # Friday 22:30 UTC -> Closed for Weekend
    friday_postclose = datetime(2026, 9, 25, 22, 30, tzinfo=timezone.utc)
    session_weekend = calendar.get_session("EURUSD", at=friday_postclose)
    assert session_weekend.is_open is False
    assert session_weekend.status == MarketSessionStatus.WEEKEND
    assert session_weekend.next_open == datetime(
        2026, 9, 27, 21, 0, tzinfo=timezone.utc
    )

    # Saturday 12:00 UTC -> Weekend Closed
    saturday = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    assert calendar.is_weekend_close("EURUSD", at=saturday) is True
    assert calendar.is_market_open("EURUSD", at=saturday) is False

    # Sunday 20:30 UTC -> Weekend Closed (Pre-open)
    sunday_preopen = datetime(2026, 9, 27, 20, 30, tzinfo=timezone.utc)
    assert calendar.is_market_open("EURUSD", at=sunday_preopen) is False

    # Sunday 21:30 UTC -> Open
    sunday_open = datetime(2026, 9, 27, 21, 30, tzinfo=timezone.utc)
    assert calendar.is_market_open("EURUSD", at=sunday_open) is True


def test_market_calendar_commodity_hours() -> None:
    """Verify Commodity schedule (Sun 23:00 - Fri 21:00 UTC, break 21-22)."""
    calendar = MarketCalendarEngine()

    # Wednesday 15:00 UTC -> Open
    wednesday_open = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
    session = calendar.get_session("XAUUSD", at=wednesday_open)
    assert session.is_open is True
    assert session.status == MarketSessionStatus.OPEN

    # Wednesday 21:30 UTC -> Break Closed
    wednesday_break = datetime(2026, 9, 23, 21, 30, tzinfo=timezone.utc)
    session_break = calendar.get_session("XAUUSD", at=wednesday_break)
    assert session_break.is_open is False
    assert session_break.status == MarketSessionStatus.BREAK
    assert session_break.next_open == datetime(2026, 9, 23, 22, 0, tzinfo=timezone.utc)

    # Wednesday 22:15 UTC -> Reopened after break
    wednesday_postbreak = datetime(2026, 9, 23, 22, 15, tzinfo=timezone.utc)
    assert calendar.is_market_open("XAUUSD", at=wednesday_postbreak) is True

    # Friday 21:15 UTC -> Weekend Closed
    friday_weekend = datetime(2026, 9, 25, 21, 15, tzinfo=timezone.utc)
    session_comm_weekend = calendar.get_session("XAUUSD", at=friday_weekend)
    assert session_comm_weekend.is_open is False
    assert session_comm_weekend.status == MarketSessionStatus.WEEKEND
    assert session_comm_weekend.next_open == datetime(
        2026, 9, 27, 23, 0, tzinfo=timezone.utc
    )


def test_market_calendar_index_hours() -> None:
    """Verify Index schedule (Sun 22:00 - Fri 20:00 UTC, daily break 20:00-22:00)."""
    calendar = MarketCalendarEngine()

    # Thursday 15:00 UTC -> Open
    thursday_open = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
    assert calendar.is_market_open("US30", at=thursday_open) is True

    # Thursday 20:30 UTC -> Break Closed
    thursday_break = datetime(2026, 9, 24, 20, 30, tzinfo=timezone.utc)
    session_break = calendar.get_session("US30", at=thursday_break)
    assert session_break.is_open is False
    assert session_break.status == MarketSessionStatus.BREAK

    # Saturday 14:00 UTC -> Weekend Closed
    saturday = datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)
    assert calendar.is_market_open("US30", at=saturday) is False


def test_market_calendar_crypto_24_7() -> None:
    """Verify Crypto CFDs trade continuously 24/7 without weekend closures."""
    calendar = MarketCalendarEngine()

    saturday = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    sunday = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)

    assert calendar.is_market_open("BTCUSD.cfd", at=saturday) is True
    assert calendar.is_market_open("ETHUSDT", at=sunday) is True
    assert calendar.is_weekend_close("BTCUSD.cfd", at=saturday) is False


def test_market_calendar_time_to_close_and_open() -> None:
    """Verify time_to_close and time_to_open countdown computations."""
    calendar = MarketCalendarEngine()

    # Friday 20:00 UTC for EURUSD (closes at 22:00 UTC) -> 2 hours
    friday_20 = datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)
    time_left = calendar.time_to_close("EURUSD", at=friday_20)
    assert time_left == timedelta(hours=2)
    assert calendar.time_to_open("EURUSD", at=friday_20) is None

    # Saturday 12:00 UTC for EURUSD (opens Sunday 21:00 UTC) -> 33 hours
    saturday_12 = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    time_to_open = calendar.time_to_open("EURUSD", at=saturday_12)
    assert time_to_open == timedelta(hours=33)
    assert calendar.time_to_close("EURUSD", at=saturday_12) is None


@pytest.mark.asyncio
async def test_cfd_client_market_hours_guard_rejects_closed_market() -> None:
    """Verify CFD client pre-trade guard blocks orders when market is closed."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()

    # Create a mock calendar engine that always reports closed weekend session
    class AlwaysClosedCalendar(MarketCalendarEngine):
        def get_session(self, symbol: str, at: datetime | None = None) -> MarketSession:
            return MarketSession(
                symbol=symbol,
                asset_class=AssetClass.FOREX,
                status=MarketSessionStatus.WEEKEND,
                is_open=False,
                current_time=datetime.now(timezone.utc),
                reason="Market closed for weekend test",
            )

    client = BitgetCfdExchangeClient(
        rest=rest,
        mapper=mapper,
        mode="ecn",
        calendar=AlwaysClosedCalendar(),
    )

    # 1. create_order rejected when closed
    with pytest.raises(ExchangeOrderRejectedError, match="TradFi CFD market is closed"):
        await client.create_order(
            symbol="EURUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.0"),
        )

    # 2. create_protection_orders rejected when closed
    with pytest.raises(ExchangeOrderRejectedError, match="TradFi CFD market is closed"):
        await client.create_protection_orders(
            symbol="EURUSD",
            side=OrderSide.BUY,
            quantity=Decimal("1.0"),
            stop_loss=Decimal("1.0800"),
        )

    # 3. close_position rejected when closed
    with pytest.raises(ExchangeOrderRejectedError, match="TradFi CFD market is closed"):
        await client.close_position(symbol="EURUSD")

    # 4. bypass_calendar_guard allows submission to reach REST client
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "orderId": "bypassed_ord",
            "symbol": "EURUSD",
            "side": "buy",
            "orderType": "market",
            "status": "new",
            "size": "1.0",
            "cTime": "1700000000000",
        },
    }
    order = await client.create_order(
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1.0"),
        bypass_calendar_guard=True,
    )
    assert order.order_id == "bypassed_ord"


@pytest.mark.asyncio
async def test_cfd_client_is_market_open_and_session() -> None:
    """Verify is_market_open and get_market_session queries on CFD client."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    tuesday = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    saturday = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)

    assert await client.is_market_open(symbol="EURUSD", at=tuesday) is True
    assert await client.is_market_open(symbol="EURUSD", at=saturday) is False

    session = await client.get_market_session(symbol="EURUSD", at=saturday)
    assert session.is_open is False
    assert session.status == MarketSessionStatus.WEEKEND
    assert session.asset_class == AssetClass.FOREX


# =============================================================================
# Phase 3: Dynamic Sizing & Lot / Pip Calculation Tests
# =============================================================================


def test_cfd_sizing_engine_contract_specs() -> None:
    """Verify CFD contract specifications across different asset classes."""
    sizing = CfdSizingEngine()

    eurusd_spec = sizing.get_contract_spec("EURUSD")
    assert eurusd_spec.asset_class == AssetClass.FOREX
    assert eurusd_spec.contract_size == Decimal("100000")
    assert eurusd_spec.pip_size == Decimal("0.0001")
    assert eurusd_spec.tick_size == Decimal("0.00001")
    assert eurusd_spec.min_lot == Decimal("0.01")

    usdjpy_spec = sizing.get_contract_spec("USDJPY")
    assert usdjpy_spec.asset_class == AssetClass.FOREX
    assert usdjpy_spec.contract_size == Decimal("100000")
    assert usdjpy_spec.pip_size == Decimal("0.01")
    assert usdjpy_spec.tick_size == Decimal("0.001")

    xau_spec = sizing.get_contract_spec("XAUUSD")
    assert xau_spec.asset_class == AssetClass.COMMODITY
    assert xau_spec.contract_size == Decimal("100")
    assert xau_spec.pip_size == Decimal("0.10")

    xag_spec = sizing.get_contract_spec("XAGUSD")
    assert xag_spec.contract_size == Decimal("5000")

    oil_spec = sizing.get_contract_spec("USOIL")
    assert oil_spec.contract_size == Decimal("1000")

    us30_spec = sizing.get_contract_spec("US30")
    assert us30_spec.asset_class == AssetClass.INDEX
    assert us30_spec.contract_size == Decimal("1")
    assert us30_spec.pip_size == Decimal("1.0")

    btc_spec = sizing.get_contract_spec("BTCUSD.cfd")
    assert btc_spec.asset_class == AssetClass.CRYPTO
    assert btc_spec.contract_size == Decimal("1")


def test_cfd_sizing_engine_pip_distance() -> None:
    """Verify pip distance computation between entry and exit prices."""
    sizing = CfdSizingEngine()

    # EURUSD 1.0850 to 1.0800 = 50 pips
    pips_eur = sizing.calculate_pip_distance(
        "EURUSD",
        entry_price=Decimal("1.0850"),
        target_price=Decimal("1.0800"),
    )
    assert pips_eur == Decimal("50")

    # USDJPY 150.50 to 150.00 = 50 pips
    pips_jpy = sizing.calculate_pip_distance(
        "USDJPY",
        entry_price=Decimal("150.50"),
        target_price=Decimal("150.00"),
    )
    assert pips_jpy == Decimal("50")

    # XAUUSD 2700.00 to 2690.00 = 100 pips (100 * $0.10)
    pips_gold = sizing.calculate_pip_distance(
        "XAUUSD",
        entry_price=Decimal("2700.00"),
        target_price=Decimal("2690.00"),
    )
    assert pips_gold == Decimal("100")


def test_cfd_sizing_engine_pip_value_per_lot() -> None:
    """Verify pip monetary value calculation per standard lot."""
    sizing = CfdSizingEngine()

    # EURUSD: 100,000 * 0.0001 = $10.00
    val_eur = sizing.calculate_pip_value_per_lot("EURUSD", price=Decimal("1.0850"))
    assert val_eur == Decimal("10.0000")

    # USDJPY at 150.00: 100,000 * 0.01 / 150.00 = $6.6666...
    val_jpy = sizing.calculate_pip_value_per_lot("USDJPY", price=Decimal("150.00"))
    expected_jpy = Decimal("1000") / Decimal("150.00")
    assert val_jpy == expected_jpy

    # EURGBP with GBP/USD conversion rate = 1.30: (100k * 0.0001) * 1.30 = $13.00
    val_eurgbp = sizing.calculate_pip_value_per_lot(
        "EURGBP",
        price=Decimal("0.8500"),
        quote_to_account_rate=Decimal("1.30"),
    )
    assert val_eurgbp == Decimal("13.0000")

    # XAUUSD: 100 * 0.10 = $10.00
    val_gold = sizing.calculate_pip_value_per_lot("XAUUSD", price=Decimal("2700.00"))
    assert val_gold == Decimal("10.00")


def test_cfd_sizing_engine_calculate_lot_size() -> None:
    """Verify dynamic lot sizing based on stop-loss distance and risk budget."""
    sizing = CfdSizingEngine()

    # Risk budget: $100
    # EURUSD: entry 1.1000, stop 1.0950 -> distance 50 pips
    # Pip value = $10/lot -> loss per lot = 50 * $10 = $500
    # Raw lots = $100 / $500 = 0.20 lots
    result = sizing.calculate_lot_size(
        symbol="EURUSD",
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0950"),
        risk_amount=Decimal("100.00"),
    )
    assert result.distance_in_pips == Decimal("50.0")
    assert result.pip_value_per_lot == Decimal("10.0000")
    assert result.calculated_lots == Decimal("0.20")
    assert result.normalized_lots == Decimal("0.20")
    # Notional = 0.20 * 100,000 * 1.1000 = $22,000
    assert result.notional_value == Decimal("22000.0000")


def test_cfd_sizing_engine_normalize_lot() -> None:
    """Verify lot normalization rules (step size, min lot, max lot)."""
    sizing = CfdSizingEngine()

    assert sizing.normalize_lot("EURUSD", Decimal("0.004")) == Decimal("0")
    assert sizing.normalize_lot("EURUSD", Decimal("0.258")) == Decimal("0.25")
    assert sizing.normalize_lot("EURUSD", Decimal("120.0")) == Decimal("100.0")
    assert sizing.normalize_lot("EURUSD", Decimal("0.0")) == Decimal("0")


def test_cfd_client_sizing_integration() -> None:
    """Verify CFD exchange client exposes sizing methods and contract specs."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    spec = client.get_contract_spec("EURUSD")
    assert isinstance(spec, CfdContractSpec)
    assert spec.contract_size == Decimal("100000")

    result = client.calculate_lot_size(
        symbol="EURUSD",
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal(
            "1.0980"
        ),  # 20 pips -> loss $200/lot -> $100 risk = 0.50 lots
        risk_amount=Decimal("100.00"),
    )
    assert isinstance(result, PipCalculationResult)
    assert result.distance_in_pips == Decimal("20.0")
    assert result.normalized_lots == Decimal("0.50")


# =============================================================================
# Phase 4: Overnight Financing / Rollover Swap & Margin Rules Tests
# =============================================================================


def test_cfd_financing_schedules() -> None:
    """Verify financing and leverage schedules across asset classes."""
    financing = CfdFinancingEngine()

    eurusd_sched = financing.get_financing_schedule("EURUSD")
    assert eurusd_sched.asset_class == AssetClass.FOREX
    assert eurusd_sched.rollover_cutoff_hour_utc == 21
    assert eurusd_sched.triple_swap_day == 2  # Wednesday
    assert eurusd_sched.max_leverage == 1000

    xau_sched = financing.get_financing_schedule("XAUUSD")
    assert xau_sched.asset_class == AssetClass.COMMODITY
    assert xau_sched.max_leverage == 800

    us30_sched = financing.get_financing_schedule("US30")
    assert us30_sched.asset_class == AssetClass.INDEX
    assert us30_sched.max_leverage == 200

    btc_sched = financing.get_financing_schedule("BTCUSD.cfd")
    assert btc_sched.asset_class == AssetClass.CRYPTO
    assert btc_sched.max_leverage == 100


def test_cfd_financing_triple_swap_detection() -> None:
    """Verify detection of 3-day triple swap rollover day."""
    financing = CfdFinancingEngine()

    # Wednesday 21:00 UTC (weekday 2) -> Triple swap
    wednesday = datetime(2026, 9, 23, 21, 0, tzinfo=timezone.utc)
    assert financing.is_triple_swap_rollover("EURUSD", at=wednesday) is True

    # Tuesday 21:00 UTC (weekday 1) -> Regular 1x swap
    tuesday = datetime(2026, 9, 22, 21, 0, tzinfo=timezone.utc)
    assert financing.is_triple_swap_rollover("EURUSD", at=tuesday) is False


def test_cfd_financing_estimate_overnight_swap() -> None:
    """Verify overnight swap charge and credit computations."""
    financing = CfdFinancingEngine()

    # Regular day (Tuesday): 1.0 lot EURUSD at 1.1000
    # Notional = $110,000. Long APR = -0.0350 (-3.5%)
    # Daily swap = $110,000 * (-0.0350 / 360) = -$10.6944
    tuesday = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
    est_regular = financing.estimate_overnight_swap(
        symbol="EURUSD",
        side=PositionSide.LONG,
        lots=Decimal("1.0"),
        price=Decimal("1.1000"),
        at=tuesday,
    )
    assert est_regular.days_multiplier == 1
    assert est_regular.is_triple_swap is False
    assert est_regular.notional == Decimal("110000.0000")
    expected_daily = Decimal("110000") * (Decimal("-0.0350") / Decimal("360"))
    assert est_regular.daily_swap_amount == expected_daily
    assert est_regular.total_swap_charge == expected_daily

    # Triple swap day (Wednesday)
    wednesday = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    est_triple = financing.estimate_overnight_swap(
        symbol="EURUSD",
        side=PositionSide.LONG,
        lots=Decimal("1.0"),
        price=Decimal("1.1000"),
        at=wednesday,
    )
    assert est_triple.days_multiplier == 3
    assert est_triple.is_triple_swap is True
    assert est_triple.total_swap_charge == expected_daily * 3


def test_cfd_financing_calculate_margin_requirement() -> None:
    """Verify required margin computation and capital sufficiency."""
    financing = CfdFinancingEngine()

    # 1.0 lot EURUSD at 1.1000 with 100x leverage: Notional = $110,000
    # Required margin = $110,000 / 100 = $1,100
    # Free margin $2,000 -> Sufficient
    margin_ok = financing.calculate_margin_requirement(
        symbol="EURUSD",
        lots=Decimal("1.0"),
        price=Decimal("1.1000"),
        leverage=100,
        free_margin=Decimal("2000.00"),
    )
    assert margin_ok.required_margin == Decimal("1100.0000")
    assert margin_ok.is_sufficient is True

    # Free margin $500 -> Insufficient
    margin_fail = financing.calculate_margin_requirement(
        symbol="EURUSD",
        lots=Decimal("1.0"),
        price=Decimal("1.1000"),
        leverage=100,
        free_margin=Decimal("500.00"),
    )
    assert margin_fail.is_sufficient is False


def test_cfd_financing_validate_leverage() -> None:
    """Verify leverage capping according to asset class boundaries."""
    financing = CfdFinancingEngine()

    # EURUSD max 1000x
    assert financing.validate_leverage("EURUSD", 1200) == 1000
    assert financing.validate_leverage("EURUSD", 50) == 50

    # XAUUSD max 800x
    assert financing.validate_leverage("XAUUSD", 1000) == 800
    assert financing.validate_leverage("XAUUSD", 500) == 500

    # BTCUSD max 100x
    assert financing.validate_leverage("BTCUSD.cfd", 150) == 100


def test_cfd_client_financing_integration() -> None:
    """Verify CFD exchange client exposes financing engine methods."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    sched = client.get_financing_schedule("EURUSD")
    assert isinstance(sched, CfdFinancingSchedule)
    assert sched.max_leverage == 1000

    est = client.estimate_overnight_swap(
        symbol="EURUSD",
        side=PositionSide.LONG,
        lots=Decimal("0.5"),
        price=Decimal("1.1000"),
    )
    assert isinstance(est, CfdOvernightSwapEstimate)
    assert est.lots == Decimal("0.5")

    margin = client.calculate_margin_requirement(
        symbol="EURUSD",
        lots=Decimal("0.5"),
        price=Decimal("1.1000"),
        leverage=50,
        free_margin=Decimal("1500.00"),
    )
    assert isinstance(margin, CfdMarginRequirement)
    assert margin.is_sufficient is True


@pytest.mark.asyncio
async def test_cfd_client_close_position_exact() -> None:
    """Verify close_position_exact routes to CFD close position endpoint."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "orderId": "cfd_close_001",
            "clientOid": "bop_cfd_exact_1",
            "symbol": "EURUSD_ecn",
            "side": "sell",
            "orderType": "market",
            "status": "closed",
            "size": "1.0",
            "cTime": "1700000000000",
        },
    }

    now = datetime.now(UTC)
    pos = Position(
        symbol="EURUSD",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("1.0850"),
        current_price=Decimal("1.0890"),
        leverage=50,
        unrealized_pnl=Decimal("40.0"),
        opened_at=now,
        updated_at=now,
        position_id="cfd_pos_001",
    )

    closed = await client.close_position_exact(
        position=pos,
        client_order_id="bop_cfd_exact_1",
    )
    assert closed.order_id == "cfd_close_001"
    assert closed.client_order_id == "bop_cfd_exact_1"
    assert rest.last_path == "/api/v3/cfd/trade/close-positions"
    assert rest.last_data is not None
    assert rest.last_data["positionId"] == "cfd_pos_001"
    assert rest.last_data["qty"] == "1.0"
    assert rest.last_data["clientOid"] == "bop_cfd_exact_1"


def test_cfd_mapper_map_candle_five_elements() -> None:
    """Verify CFD mapper supports 5-element candle tuple with zero volume."""
    mapper = BitgetCfdMapper()
    row = (
        "1700000000000",
        "1.0850",
        "1.0870",
        "1.0840",
        "1.0865",
    )
    candle = mapper.map_candle(row, symbol="EURUSD.s", interval=Interval.M15)
    assert candle.symbol == "EURUSD"
    assert candle.interval == Interval.M15
    assert candle.open_price == Decimal("1.0850")
    assert candle.high_price == Decimal("1.0870")
    assert candle.low_price == Decimal("1.0840")
    assert candle.close_price == Decimal("1.0865")
    assert candle.volume == Decimal("0")


@pytest.mark.asyncio
async def test_cfd_client_get_trading_symbols() -> None:
    """Verify get_trading_symbols queries tickers endpoint and deduplicates symbols."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="zero_fee")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {"symbol": "EURUSD.s", "lastPr": "1.0850"},
            {"symbol": "EURUSD.pro", "lastPr": "1.0850"},
            {"symbol": "XAUUSD.s", "lastPr": "2650.00"},
            {"symbol": "US30.s", "lastPr": "42000.00"},
            {"symbol": "EURGBP.s", "lastPr": "0.8500"},
        ],
    }

    symbols = await client.get_trading_symbols(quote_asset="USD")
    assert rest.last_path == "/api/v3/cfd/market/tickers"
    assert "EURUSD" in symbols
    assert "XAUUSD" in symbols
    assert "US30" in symbols
    assert "EURGBP" in symbols
    # Ensure deduplicated
    assert symbols.count("EURUSD") == 1

    gbp_symbols = await client.get_trading_symbols(quote_asset="GBP")
    assert "EURGBP" in gbp_symbols
    assert "EURUSD" not in gbp_symbols


@pytest.mark.asyncio
async def test_cfd_client_get_candles() -> None:
    """Verify get_candles queries history-candlestick endpoint with parameters."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="zero_fee")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            [
                "1700000000000",
                "1.0850",
                "1.0870",
                "1.0840",
                "1.0865",
            ]
        ],
    }

    candles = await client.get_candles(
        symbol="EURUSD",
        interval=Interval.M15,
        limit=50,
    )
    assert rest.last_path == "/api/v3/cfd/market/history-candlestick"
    assert rest.last_params is not None
    assert rest.last_params["symbol"] == "EURUSD.s"
    assert rest.last_params["interval"] == "15m"
    assert rest.last_params["side"] == "buy"
    assert len(candles) == 1
    assert candles[0].close_price == Decimal("1.0865")
    assert candles[0].volume == Decimal("0")


@pytest.mark.asyncio
async def test_cfd_client_get_candles_backward_pagination() -> None:
    """Verify get_candles paginates backward when limit exceeds 100."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="zero_fee")

    batch_1 = [
        [
            str(100_000 + i * 1_000),
            "1.0800",
            "1.0850",
            "1.0790",
            "1.0820",
        ]
        for i in range(100)
    ]
    batch_2 = [
        [
            str(50_000 + i * 1_000),
            "1.0750",
            "1.0810",
            "1.0740",
            "1.0790",
        ]
        for i in range(50)
    ]

    rest.canned_responses = [
        {"code": "00000", "msg": "success", "data": batch_1},
        {"code": "00000", "msg": "success", "data": batch_2},
    ]

    candles = await client.get_candles(
        symbol="EURUSD",
        interval=Interval.M15,
        limit=150,
    )

    assert len(candles) == 150
    assert len(rest.history) == 2
    assert candles[0].close_price == Decimal("1.0790")
    assert candles[-1].close_price == Decimal("1.0820")


@pytest.mark.asyncio
async def test_cfd_client_get_market_entry_rules() -> None:
    """Verify get_market_entry_rules loads specification from sizing engine."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="zero_fee")

    rules = await client.get_market_entry_rules(symbol="EURUSD")
    assert rules.symbol == "EURUSD"
    assert rules.market_min_quantity == Decimal("0.01")
    assert rules.market_max_quantity == Decimal("100.0")
    assert rules.market_quantity_step == Decimal("0.01")
    # EURUSD: pip_size is 0.0001, but authoritative price_tick_size must be 0.00001
    assert rules.price_tick_size == Decimal("0.00001")

    # XAUUSD: pip_size is 0.10, but authoritative price_tick_size must be 0.01
    xau_rules = await client.get_market_entry_rules(symbol="XAUUSD")
    assert xau_rules.price_tick_size == Decimal("0.01")

    # USDJPY: pip_size is 0.01, but authoritative price_tick_size must be 0.001
    jpy_rules = await client.get_market_entry_rules(symbol="USDJPY")
    assert jpy_rules.price_tick_size == Decimal("0.001")
