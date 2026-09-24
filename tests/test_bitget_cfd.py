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
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.exchange_settings import ExchangeSettings
from botragram.config.risk_settings import RiskSettings
from botragram.engine import (
    CfdFinancingEngine,
    CfdSizingEngine,
    MarketCalendarEngine,
    PortfolioEngine,
    RiskEngine,
    TradingEngine,
)
from botragram.enums import (
    AssetClass,
    CfdInstrumentStatus,
    ExchangeType,
    Interval,
    MarketSessionStatus,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
    StrategyType,
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
    BitgetFuturesExchangeClient,
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
    Signal,
)
from botragram.services import LiveEntryRiskEvaluationService


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
        self.post_bodies: list[dict[str, object]] = []
        self.last_method = ""
        self.last_path = ""
        self.last_post_path = ""
        self.last_params: QueryParams | None = None
        self.last_data: dict[str, object] | None = None
        self.canned_response: JsonResponse = {
            "code": "00000",
            "msg": "success",
            "data": {},
        }
        self.canned_responses: list[JsonResponse] = []
        self.positions_store: list[dict[str, object]] | None = None
        self.auto_reconcile_positions: bool = False

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
        if (
            self.positions_store is not None
            and path == "/api/v3/cfd/trade/current-positions"
        ):
            return self._validate_response_envelope(
                {
                    "code": "00000",
                    "msg": "success",
                    "data": list(self.positions_store),
                }
            )
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
        if data is not None:
            self.post_bodies.append(dict(data))
        self.last_method = "POST"
        self.last_path = path
        self.last_post_path = path
        self.last_params = params
        self.last_data = data
        if (
            self.auto_reconcile_positions
            and self.positions_store is not None
            and path == "/api/v3/cfd/trade/close-positions"
            and data is not None
        ):
            target_pid = str(data.get("positionId", ""))
            close_qty = Decimal(str(data.get("qty", "0")))
            remaining: list[dict[str, object]] = []
            for pos in self.positions_store:
                if str(pos.get("positionId", "")) == target_pid:
                    curr_qty = Decimal(str(pos.get("total", "0")))
                    rem_qty = curr_qty - close_qty
                    if rem_qty > Decimal("0"):
                        updated_pos = dict(pos)
                        updated_pos["total"] = str(rem_qty)
                        remaining.append(updated_pos)
                else:
                    remaining.append(pos)
            self.positions_store = remaining
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

    # Case-insensitive mode
    assert mapper.to_vendor_symbol("XAUUSD", mode="ZERO_FEE") == "XAUUSD.s"
    assert mapper.to_vendor_symbol("EURUSD", mode="Pro") == "EURUSD.pro"
    assert mapper.to_vendor_symbol("US100", mode="ECN") == "US100"

    # Prevent double suffix if symbol already has suffix
    assert mapper.to_vendor_symbol("XAUUSD.s", mode="zero_fee") == "XAUUSD.s"
    assert mapper.to_vendor_symbol("EURUSD.pro", mode="pro") == "EURUSD.pro"
    assert mapper.to_vendor_symbol("XAUUSD.s", mode="ecn") == "XAUUSD"
    assert mapper.to_vendor_symbol("EURUSD.pro", mode="ecn") == "EURUSD"

    # Invalid mode fails fast
    with pytest.raises(ValueError, match="Invalid CFD mode"):
        mapper.to_vendor_symbol("XAUUSD", mode="unsupported")


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


def test_cfd_mapper_enable_mapping() -> None:
    """Test Bitget CFD enable mapping: 2=tradable, 1=close-only, 0=prohibited."""
    mapper = BitgetCfdMapper()
    base_payload = {
        "symbol": "EURUSD.s",
        "contractSize": "100000",
        "tickSize": "0.00001",
        "pipSize": "0.0001",
        "minVolume": "0.01",
        "maxVolume": "100.0",
        "stepVolume": "0.01",
    }

    # "2" => tradable (True / TRADING_ALLOWED)
    spec_tradable = mapper.map_instrument_spec({**base_payload, "enable": "2"})
    assert spec_tradable.enable is True
    assert spec_tradable.status is CfdInstrumentStatus.TRADING_ALLOWED
    assert spec_tradable.is_tradable is True
    assert spec_tradable.is_close_only is False
    assert spec_tradable.is_disabled is False

    # "1" => close-only (False / CLOSE_ONLY)
    spec_close_only = mapper.map_instrument_spec({**base_payload, "enable": "1"})
    assert spec_close_only.enable is False
    assert spec_close_only.status is CfdInstrumentStatus.CLOSE_ONLY
    assert spec_close_only.is_tradable is False
    assert spec_close_only.is_close_only is True
    assert spec_close_only.is_disabled is False

    # "0" => prohibited (False / DISABLED)
    spec_prohibited = mapper.map_instrument_spec({**base_payload, "enable": "0"})
    assert spec_prohibited.enable is False
    assert spec_prohibited.status is CfdInstrumentStatus.DISABLED
    assert spec_prohibited.is_tradable is False
    assert spec_prohibited.is_close_only is False
    assert spec_prohibited.is_disabled is True

    # Unknown / invalid / missing => fail closed (False / DISABLED)
    spec_unknown = mapper.map_instrument_spec({**base_payload, "enable": "99"})
    assert spec_unknown.enable is False
    assert spec_unknown.status is CfdInstrumentStatus.DISABLED
    assert spec_unknown.is_tradable is False
    assert spec_unknown.is_close_only is False
    assert spec_unknown.is_disabled is True

    spec_invalid = mapper.map_instrument_spec({**base_payload, "enable": "unknown"})
    assert spec_invalid.enable is False
    assert spec_invalid.status is CfdInstrumentStatus.DISABLED

    spec_missing = mapper.map_instrument_spec({**base_payload})
    assert spec_missing.enable is False
    assert spec_missing.status is CfdInstrumentStatus.DISABLED


def test_cfd_mapper_map_position_actual_api() -> None:
    """Verify map_position parses actual Bitget CFD current-positions payload."""
    mapper = BitgetCfdMapper()
    payload = {
        "positionId": "pos-cfd-real-12345",
        "symbol": "EURUSD.s",
        "side": "LONG",
        "qty": "2.5",
        "openPrice": "1.0850",
        "takeProfit": "1.0950",
        "stopLoss": "1.0800",
        "interest": "0.15",
        "unrealizedPnl": "125.00",
        "totalProfit": "125.00",
    }
    position = mapper.map_position(payload)
    assert position.symbol == "EURUSD"
    assert position.side is PositionSide.LONG
    assert position.quantity == Decimal("2.5")
    assert position.entry_price == Decimal("1.0850")
    assert position.position_id == "pos-cfd-real-12345"
    assert position.unrealized_pnl == Decimal("125.00")

    # Short position
    payload_short = {
        "positionId": "pos-cfd-short-67890",
        "symbol": "USDJPY",
        "side": "SHORT",
        "qty": "1.0",
        "openPrice": "155.20",
        "unrealizedPnl": "-45.00",
    }
    pos_short = mapper.map_position(payload_short)
    assert pos_short.symbol == "USDJPY"
    assert pos_short.side is PositionSide.SHORT
    assert pos_short.quantity == Decimal("1.0")
    assert pos_short.entry_price == Decimal("155.20")
    assert pos_short.position_id == "pos-cfd-short-67890"
    assert pos_short.unrealized_pnl == Decimal("-45.00")


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
    # create_order POSTs to place-order, then calls get_order to reconcile.
    # Verify the first request in history was the POST to place-order.
    assert rest.history[0] == ("POST", "/api/v3/cfd/trade/place-order"), (
        f"Expected place-order as first request, got: {rest.history[0]}"
    )
    # Verify place-order produced a well-formed Order with correct symbol.
    assert order.symbol == "EURUSD"

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
    # Verify a POST to place-order was made (create_order then calls get_order)
    assert any(
        method == "POST" and path == "/api/v3/cfd/trade/place-order"
        for method, path in rest.history
    ), f"place-order POST not found in history: {rest.history}"
    # Verify the place-order payload used 'qty' not 'size'
    assert rest.post_bodies, "No POST body recorded"
    place_body = rest.post_bodies[0]
    assert place_body.get("qty") == "0.15", f"qty not in place-order body: {place_body}"
    assert "size" not in place_body, (
        f"'size' must not appear in place-order body: {place_body}"
    )


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
            "data": None,
        },
    ]

    closed = await client.close_position(
        symbol="XAUUSD",
        client_order_id="close_client_999",
        bypass_calendar_guard=True,
    )

    assert closed.order_id == ""
    assert closed.client_order_id == "close_client_999"
    assert closed.status is OrderStatus.FILLED
    assert closed.side is OrderSide.SELL
    assert closed.quantity == Decimal("0.25")
    assert rest.last_post_path == "/api/v3/cfd/trade/close-positions"
    assert ("GET", "/api/v3/cfd/trade/current-positions") in rest.history
    assert rest.last_data is not None
    assert rest.last_data == {
        "positionId": "pos-cfd-resolved-789",
        "qty": "0.25",
    }
    assert "clientOid" not in rest.last_data


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


def test_exchange_settings_cfd_mode_validation() -> None:
    """Verify ExchangeSettings validates and normalizes cfd_mode."""
    # Default is ecn
    default_settings = ExchangeSettings(exchange=ExchangeType.BITGET)
    assert default_settings.cfd_mode == "ecn"

    # Accepted values (case-insensitive)
    assert ExchangeSettings(cfd_mode="ecn").cfd_mode == "ecn"
    assert ExchangeSettings(cfd_mode="ECN").cfd_mode == "ecn"
    assert ExchangeSettings(cfd_mode="zero_fee").cfd_mode == "zero_fee"
    assert ExchangeSettings(cfd_mode="ZERO_FEE").cfd_mode == "zero_fee"
    assert ExchangeSettings(cfd_mode="pro").cfd_mode == "pro"
    assert ExchangeSettings(cfd_mode="PRO").cfd_mode == "pro"

    # Invalid values fail fast
    with pytest.raises(ValueError, match="Invalid CFD mode"):
        ExchangeSettings(cfd_mode="invalid_mode")
    with pytest.raises(ValueError, match="Invalid CFD mode"):
        ExchangeSettings(cfd_mode="")


def test_cfd_client_init_mode_validation() -> None:
    """Verify BitgetCfdExchangeClient validates mode on initialization."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()

    # Default is ecn
    client_default = BitgetCfdExchangeClient(rest=rest, mapper=mapper)
    assert client_default.mode == "ecn"

    # Explicit accepted values
    client_zf = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ZERO_FEE")
    assert client_zf.mode == "zero_fee"

    client_pro = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="Pro")
    assert client_pro.mode == "pro"

    # Invalid value rejected
    with pytest.raises(ValueError, match="Invalid CFD mode"):
        BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="vip")


def test_exchange_factory_bitget_cfd_mode_configuration() -> None:
    """Verify ExchangeFactory forwards cfd_mode correctly to CFD client."""
    rest = MockBitgetRestClient()

    # Default cfd_mode
    client_ecn = ExchangeFactory.create_exchange_client(
        exchange_type=ExchangeType.BITGET,
        rest_client=rest,
        market_type=MarketType.CFD,
    )
    assert isinstance(client_ecn, BitgetCfdExchangeClient)
    assert client_ecn.mode == "ecn"

    # Explicit cfd_mode zero_fee
    client_zf = ExchangeFactory.create_exchange_client(
        exchange_type=ExchangeType.BITGET,
        rest_client=rest,
        market_type=MarketType.CFD,
        cfd_mode="zero_fee",
    )
    assert isinstance(client_zf, BitgetCfdExchangeClient)
    assert client_zf.mode == "zero_fee"

    # Explicit cfd_mode pro
    client_pro = ExchangeFactory.create_exchange_client(
        exchange_type=ExchangeType.BITGET,
        rest_client=rest,
        market_type=MarketType.CFD,
        cfd_mode="pro",
    )
    assert isinstance(client_pro, BitgetCfdExchangeClient)
    assert client_pro.mode == "pro"

    # ExchangeFactory.create with cfd_mode
    full_client, _ = ExchangeFactory.create(
        exchange_type=ExchangeType.BITGET,
        rest_base_url="https://api.bitget.com",
        websocket_base_url="wss://ws.bitget.com",
        market_type=MarketType.CFD,
        cfd_mode="zero_fee",
    )
    assert isinstance(full_client, BitgetCfdExchangeClient)
    assert full_client.mode == "zero_fee"

    # Futures client remains unaffected
    futures_client = ExchangeFactory.create_exchange_client(
        exchange_type=ExchangeType.BITGET,
        rest_client=rest,
        market_type=MarketType.FUTURES,
        cfd_mode="zero_fee",
    )
    assert isinstance(futures_client, BitgetFuturesExchangeClient)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_vendor_symbol"),
    [
        ("ecn", "XAUUSD"),
        ("zero_fee", "XAUUSD.s"),
        ("pro", "XAUUSD.pro"),
    ],
)
async def test_cfd_client_create_order_sends_vendor_symbol_by_mode(
    mode: str,
    expected_vendor_symbol: str,
) -> None:
    """Verify create_order sends vendor symbol according to CFD account mode."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode=mode)

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "orderId": "order_cfd_test_mode",
            "clientOid": "cl_test_mode",
            "symbol": expected_vendor_symbol,
            "side": "buy",
            "orderType": "market",
            "status": "new",
            "size": "0.1",
            "cTime": "1700000000000",
        },
    }

    order = await client.create_order(
        symbol="XAUUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
        client_order_id="cl_test_mode",
        bypass_calendar_guard=True,
    )

    assert rest.post_bodies, "No POST body was captured"
    assert rest.post_bodies[0]["symbol"] == expected_vendor_symbol
    # Returned domain Order symbol must remain canonical internal symbol
    assert order.symbol == "XAUUSD"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_vendor_symbol"),
    [
        ("ecn", "XAUUSD"),
        ("zero_fee", "XAUUSD.s"),
        ("pro", "XAUUSD.pro"),
    ],
)
async def test_cfd_client_create_order_sends_vendor_symbol_by_mode_trx_id_only_unfilled(
    mode: str,
    expected_vendor_symbol: str,
) -> None:
    """Verify place-order returning only trxId sends mode vendor symbol
    and reconciles via unfilled-order.
    """
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode=mode)

    trx_id = f"trx_{mode}_999"
    actual_order_id = f"ord_{mode}_actual_999"

    # 1. place-order returns ONLY trxId
    # 2. unfilled-order returns order matching trxId
    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "trxId": trx_id,
            },
        },
        {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "orderId": actual_order_id,
                    "trxId": trx_id,
                    "symbol": expected_vendor_symbol,
                    "side": "buy",
                    "orderType": "market",
                    "qty": "0.1",
                    "status": "new",
                    "cTime": "1700000000000",
                }
            ],
        },
    ]

    order = await client.create_order(
        symbol="XAUUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
        client_order_id=f"cl_{mode}_999",
        bypass_calendar_guard=True,
    )

    # 1. Verify vendor symbol sent in POST place-order payload matches the mode
    assert rest.post_bodies, "No POST body was captured"
    assert rest.post_bodies[0]["symbol"] == expected_vendor_symbol
    # 2. Verify trxId successfully reconciled to actual venue orderId
    assert order.order_id == actual_order_id
    assert order.execution_order_id == trx_id
    # 3. Domain Order symbol remains internal canonical
    assert order.symbol == "XAUUSD"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_vendor_symbol"),
    [
        ("ecn", "XAUUSD"),
        ("zero_fee", "XAUUSD.s"),
        ("pro", "XAUUSD.pro"),
    ],
)
async def test_cfd_client_create_order_sends_vendor_symbol_by_mode_trx_id_only_history(
    mode: str,
    expected_vendor_symbol: str,
) -> None:
    """Verify place-order returning only trxId sends mode vendor symbol
    and reconciles via history-order.
    """
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode=mode)

    trx_id = f"trx_{mode}_hist_888"
    actual_order_id = f"ord_{mode}_hist_888"

    # 1. place-order returns ONLY trxId
    # 2. unfilled-order returns empty list
    # 3. history-order returns order matching trxId
    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "trxId": trx_id,
            },
        },
        {
            "code": "00000",
            "msg": "success",
            "data": [],
        },
        {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "orderId": actual_order_id,
                    "trxId": trx_id,
                    "symbol": expected_vendor_symbol,
                    "side": "buy",
                    "orderType": "market",
                    "qty": "0.1",
                    "status": "filled",
                    "cTime": "1700000000000",
                }
            ],
        },
    ]

    order = await client.create_order(
        symbol="XAUUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
        client_order_id=f"cl_{mode}_888",
        bypass_calendar_guard=True,
    )

    assert rest.post_bodies, "No POST body was captured"
    assert rest.post_bodies[0]["symbol"] == expected_vendor_symbol
    assert order.order_id == actual_order_id
    assert order.execution_order_id == trx_id
    assert order.symbol == "XAUUSD"


@pytest.mark.asyncio
async def test_cfd_enable_semantics_and_live_entry_guard() -> None:
    """Verify enable=0, enable=1, enable=2 semantics and LIVE entry guard."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()

    base_payload = {
        "symbol": "EURUSD",
        "contractSize": "100000",
        "tickSize": "0.00001",
        "pipSize": "0.0001",
        "minVolume": "0.01",
        "maxVolume": "100.0",
        "stepVolume": "0.01",
    }

    # 1. enable=2 -> TRADING_ALLOWED (tradable)
    spec_tradable = mapper.map_instrument_spec({**base_payload, "enable": "2"})
    assert spec_tradable.enable is True
    assert spec_tradable.status is CfdInstrumentStatus.TRADING_ALLOWED
    assert spec_tradable.is_tradable is True
    assert spec_tradable.is_close_only is False
    assert spec_tradable.is_disabled is False

    # 2. enable=1 -> CLOSE_ONLY (close-only)
    spec_close_only = mapper.map_instrument_spec({**base_payload, "enable": "1"})
    assert spec_close_only.enable is False
    assert spec_close_only.status is CfdInstrumentStatus.CLOSE_ONLY
    assert spec_close_only.is_tradable is False
    assert spec_close_only.is_close_only is True
    assert spec_close_only.is_disabled is False

    # 3. enable=0 -> DISABLED (prohibited)
    spec_disabled = mapper.map_instrument_spec({**base_payload, "enable": "0"})
    assert spec_disabled.enable is False
    assert spec_disabled.status is CfdInstrumentStatus.DISABLED
    assert spec_disabled.is_tradable is False
    assert spec_disabled.is_close_only is False
    assert spec_disabled.is_disabled is True

    # 4. LIVE entry: client with is_live=True
    client_live = BitgetCfdExchangeClient(
        rest=rest, mapper=mapper, mode="ecn", is_live=True
    )

    # When spec is TRADING_ALLOWED (enable=2), LIVE contract spec succeeds
    setattr(client_live, "_instruments_cache", {"EURUSD": spec_tradable})
    setattr(client_live, "_instruments_cache_time", datetime.now(timezone.utc))
    live_spec = client_live.get_contract_spec("EURUSD")
    assert live_spec.status is CfdInstrumentStatus.TRADING_ALLOWED
    sizing_spec = client_live.sizing.get_contract_spec("EURUSD")
    assert sizing_spec.status is CfdInstrumentStatus.TRADING_ALLOWED

    # When spec is CLOSE_ONLY (enable=1), LIVE entry is rejected fail-closed
    setattr(client_live, "_instruments_cache", {"EURUSD": spec_close_only})
    with pytest.raises(ExchangeError, match="disabled"):
        client_live.get_contract_spec("EURUSD")
    with pytest.raises(ValueError, match="disabled on exchange"):
        client_live.sizing.get_contract_spec("EURUSD")

    # But position management / close path remains accessible and functional
    assert spec_close_only.is_close_only
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": None,
    }
    pos = Position(
        symbol="EURUSD",
        side=PositionSide.LONG,
        quantity=Decimal("0.5"),
        entry_price=Decimal("1.0850"),
        current_price=Decimal("1.0890"),
        leverage=50,
        unrealized_pnl=Decimal("20.0"),
        opened_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        position_id="pos_close_only_99",
    )
    close_order = await client_live.close_position_exact(
        position=pos,
        client_order_id="close_cl_1",
    )
    assert close_order.order_id == ""
    assert close_order.client_order_id == "close_cl_1"
    assert close_order.status is OrderStatus.FILLED
    assert rest.last_data is not None
    assert rest.last_data == {
        "positionId": "pos_close_only_99",
        "qty": "0.5",
    }
    assert "clientOid" not in rest.last_data

    # When spec is DISABLED (enable=0), LIVE entry is rejected fail-closed
    setattr(client_live, "_instruments_cache", {"EURUSD": spec_disabled})
    with pytest.raises(ExchangeError, match="disabled"):
        client_live.get_contract_spec("EURUSD")
    with pytest.raises(ValueError, match="disabled on exchange"):
        client_live.sizing.get_contract_spec("EURUSD")


def test_settings_manager_bitget_cfd_mode_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify settings manager pipeline parses BITGET_CFD_MODE from environment."""
    from botragram.app.environment_provider import EnvironmentProvider
    from botragram.app.settings_manager import SettingsManager

    env_file = tmp_path / "test.env"
    env_file.write_text(
        "ACTIVE_EXCHANGE=BITGET\nBITGET_MARKET_TYPE=CFD\nBITGET_CFD_MODE=zero_fee\n",
        encoding="utf-8",
    )

    env = EnvironmentProvider(env_path=str(env_file))
    assert env.get_bitget_cfd_mode() == "zero_fee"

    mgr = SettingsManager(environment_provider=env)
    settings = mgr.load_exchange_settings()
    assert settings.cfd_mode == "zero_fee"

    # Default when BITGET_CFD_MODE is omitted
    monkeypatch.delenv("BITGET_CFD_MODE", raising=False)
    env_default_file = tmp_path / "default.env"
    env_default_file.write_text(
        "ACTIVE_EXCHANGE=BITGET\nBITGET_MARKET_TYPE=CFD\n",
        encoding="utf-8",
    )
    env_default = EnvironmentProvider(env_path=str(env_default_file))
    assert env_default.get_bitget_cfd_mode() == "ecn"
    mgr_default = SettingsManager(environment_provider=env_default)
    assert mgr_default.load_exchange_settings().cfd_mode == "ecn"

    # Invalid mode in environment raises ValueError on load_exchange_settings
    env_invalid_file = tmp_path / "invalid.env"
    env_invalid_file.write_text(
        "ACTIVE_EXCHANGE=BITGET\n"
        "BITGET_MARKET_TYPE=CFD\n"
        "BITGET_CFD_MODE=invalid_value\n",
        encoding="utf-8",
    )
    env_invalid = EnvironmentProvider(env_path=str(env_invalid_file))
    mgr_invalid = SettingsManager(environment_provider=env_invalid)
    with pytest.raises(ValueError, match="Invalid CFD mode"):
        mgr_invalid.load_exchange_settings()


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
        "data": None,
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
    assert closed.order_id == ""
    assert closed.client_order_id == "bop_cfd_exact_1"
    assert closed.status is OrderStatus.FILLED
    assert closed.side is OrderSide.SELL
    assert closed.quantity == Decimal("1.0")
    assert rest.last_post_path == "/api/v3/cfd/trade/close-positions"
    assert ("GET", "/api/v3/cfd/trade/current-positions") in rest.history
    assert rest.last_data is not None
    assert rest.last_data == {
        "positionId": "cfd_pos_001",
        "qty": "1.0",
    }
    assert "clientOid" not in rest.last_data


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


@pytest.mark.asyncio
async def test_cfd_client_create_order_trx_id_only_resolved_via_unfilled() -> None:
    """Verify place-order returning only trxId resolves orderId via unfilled-order."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    # 1. place-order returns only trxId
    # 2. unfilled-order returns the order with real orderId and matching trxId
    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "trxId": "trx_cfd_1001",
            },
        },
        {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "orderId": "actual_ord_1001",
                    "trxId": "trx_cfd_1001",
                    "symbol": "EURUSD",
                    "side": "buy",
                    "orderType": "market",
                    "qty": "0.1",
                    "status": "new",
                    "cTime": "1700000000000",
                }
            ],
        },
    ]

    order = await client.create_order(
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
    )
    assert order.order_id == "actual_ord_1001"
    assert order.execution_order_id == "trx_cfd_1001"
    assert order.order_id != "trx_cfd_1001"  # No fake orderId
    # Verify clientOid was NOT sent in place-order body
    assert rest.last_data is not None
    assert "clientOid" not in rest.last_data


@pytest.mark.asyncio
async def test_cfd_client_create_order_trx_id_only_resolved_via_history() -> None:
    """Verify place-order returning only trxId resolves orderId via history-order."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    # 1. place-order returns only trxId
    # 2. unfilled-order returns empty list
    # 3. history-order returns filled order with matching trxId
    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "trxId": "trx_cfd_1002",
            },
        },
        {
            "code": "00000",
            "msg": "success",
            "data": [],
        },
        {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "orderId": "actual_ord_1002",
                    "trxId": "trx_cfd_1002",
                    "symbol": "EURUSD",
                    "side": "buy",
                    "orderType": "market",
                    "qty": "0.1",
                    "status": "filled",
                    "cTime": "1700000000000",
                }
            ],
        },
    ]

    order = await client.create_order(
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
    )
    assert order.order_id == "actual_ord_1002"
    assert order.execution_order_id == "trx_cfd_1002"
    assert order.status is OrderStatus.FILLED


@pytest.mark.asyncio
async def test_cfd_client_create_order_trx_id_not_found_fails_unknown() -> None:
    """Verify unresolved order identity raises outcome unknown error."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    # 1. place-order returns only trxId
    # 2. unfilled-order returns empty list
    # 3. history-order returns empty list
    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "trxId": "trx_cfd_unresolved",
            },
        },
        {
            "code": "00000",
            "msg": "success",
            "data": [],
        },
        {
            "code": "00000",
            "msg": "success",
            "data": [],
        },
    ]

    with pytest.raises(ExchangeOrderOutcomeUnknownError):
        await client.create_order(
            symbol="EURUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )


@pytest.mark.asyncio
async def test_cfd_client_cache_ttl_expiry_enforced() -> None:
    """Verify cache TTL is strictly enforced and expired cache fails closed in LIVE."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn", is_live=True)

    spec = CfdContractSpec(
        symbol="EURUSD",
        asset_class=AssetClass.FOREX,
        contract_size=Decimal("100000"),
        pip_size=Decimal("0.0001"),
        tick_size=Decimal("0.00001"),
        enable=True,
    )

    # 1. Fresh cache is valid
    setattr(client, "_instruments_cache", {"EURUSD": spec})
    setattr(client, "_instruments_cache_time", datetime.now(timezone.utc))
    assert client.get_cached_contract_spec("EURUSD") is spec

    # 2. Expired cache returns None
    setattr(
        client,
        "_instruments_cache_time",
        datetime.now(timezone.utc) - timedelta(seconds=301),
    )
    assert client.get_cached_contract_spec("EURUSD") is None

    # 3. Sizing engine with LIVE mode fails closed when cache is expired
    match_msg = "Authoritative CFD instrument metadata unavailable"
    with pytest.raises(ValueError, match=match_msg):
        client.sizing.get_contract_spec("EURUSD")


@pytest.mark.asyncio
async def test_cfd_client_history_order_limit_normalized_to_50() -> None:
    """Verify Bitget CFD history-order limit is normalized to maximum 50."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [],
    }

    # get_trades with limit=100 must normalize to 50
    await client.get_trades(symbol="EURUSD", limit=100)
    assert rest.last_params is not None
    assert rest.last_params.get("limit") == 50

    # get_history_orders with limit=100 must normalize to 50
    await client.get_history_orders(symbol="EURUSD", limit=100)
    assert rest.last_params is not None
    assert rest.last_params.get("limit") == 50


# =============================================================================
# CFD Metadata TTL / Refresh Tests
# =============================================================================
@pytest.mark.asyncio
async def test_cfd_refresh_metadata_fresh_cache_skips_network() -> None:
    """Fresh cache (< 300s) executes without additional network calls."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, is_live=True)

    spec = CfdContractSpec(
        symbol="XAUUSD",
        asset_class=AssetClass.COMMODITY,
        contract_size=Decimal("100"),
        pip_size=Decimal("0.01"),
        tick_size=Decimal("0.01"),
        min_lot=Decimal("0.01"),
        max_lot=Decimal("50"),
        lot_step=Decimal("0.01"),
        enable=True,
    )
    setattr(client, "_instruments_cache", {"XAUUSD": spec})
    setattr(client, "_instruments_cache_time", datetime.now(timezone.utc))

    # Calling refresh_instrument_metadata on fresh cache does not make REST calls
    await client.refresh_instrument_metadata(symbol="XAUUSD")
    assert not any(path == "/api/v3/cfd/market/contracts" for _, path in rest.history)
    assert client.get_cached_contract_spec("XAUUSD") is spec


@pytest.mark.asyncio
async def test_cfd_refresh_metadata_expired_cache_refreshes_from_exchange() -> None:
    """Expired cache (> 300s) triggers async refresh before sizing and updates cache."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, is_live=True)

    old_spec = CfdContractSpec(
        symbol="XAUUSD",
        asset_class=AssetClass.COMMODITY,
        contract_size=Decimal("100"),
        pip_size=Decimal("0.01"),
        tick_size=Decimal("0.01"),
        min_lot=Decimal("0.01"),
        max_lot=Decimal("50"),
        lot_step=Decimal("0.01"),
        enable=True,
    )
    setattr(client, "_instruments_cache", {"XAUUSD": old_spec})
    setattr(
        client,
        "_instruments_cache_time",
        datetime.now(timezone.utc) - timedelta(seconds=305),
    )

    # Initial state: cache expired -> get_cached_contract_spec is None
    assert client.get_cached_contract_spec("XAUUSD") is None

    # Exchange returns updated metadata with new tick_size and max_lots
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "XAUUSD",
                "assetClass": "COMMODITY",
                "contractSize": "100",
                "tickSize": "0.001",
                "pipSize": "0.01",
                "minVolume": "0.01",
                "maxVolume": "100",
                "stepVolume": "0.01",
                "enable": "2",
            }
        ],
    }

    # Refresh
    await client.refresh_instrument_metadata(symbol="XAUUSD")

    # REST call was executed
    assert any(path == "/api/v3/cfd/account/instruments" for _, path in rest.history)

    # Cache is refreshed and unexpired
    cached = client.get_cached_contract_spec("XAUUSD")
    assert cached is not None
    assert cached.tick_size == Decimal("0.001")
    assert cached.max_lot == Decimal("100")

    # Sizing engine resolves the updated metadata without failing
    sizing_spec = client.sizing.get_contract_spec("XAUUSD")
    assert sizing_spec.tick_size == Decimal("0.001")


@pytest.mark.asyncio
async def test_cfd_refresh_metadata_failure_fails_closed_in_live() -> None:
    """Failed metadata refresh in LIVE mode fails closed and never falls back."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, is_live=True)

    # Expired cache
    setattr(client, "_instruments_cache", {})
    setattr(
        client,
        "_instruments_cache_time",
        datetime.now(timezone.utc) - timedelta(seconds=400),
    )

    rest.canned_response = {
        "code": "40001",
        "msg": "Network failure on exchange",
        "data": [],
    }

    with pytest.raises(
        ExchangeError, match="Failed to fetch authoritative CFD instruments"
    ):
        await client.refresh_instrument_metadata(symbol="XAUUSD")

    # Sizing engine remains fail closed
    with pytest.raises(
        ValueError, match="Authoritative CFD instrument metadata unavailable"
    ):
        client.sizing.get_contract_spec("XAUUSD")


@pytest.mark.asyncio
async def test_cfd_refresh_metadata_paper_mode_preserves_deterministic_fallback() -> (
    None
):
    """Non-live PAPER/TEST mode preserves existing deterministic behavior."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, is_live=False)

    # No network response (canned response returns empty)
    rest.canned_response = {
        "code": "50000",
        "msg": "error",
        "data": [],
    }

    # In paper mode, refresh does not raise ExchangeError
    await client.refresh_instrument_metadata(symbol="BTCUSD")

    # Sizing resolves fallback deterministic spec
    spec = client.sizing.get_contract_spec("BTCUSD")
    assert spec.symbol == "BTCUSD"
    assert spec.asset_class == AssetClass.CRYPTO


@pytest.mark.asyncio
async def test_live_entry_risk_evaluation_service_refreshes_expired_cfd_metadata() -> (
    None
):
    """LiveEntryRiskEvaluationService refreshes expired metadata before LIVE sizing."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, is_live=True)

    # Populate expired cache
    spec = CfdContractSpec(
        symbol="XAUUSD",
        asset_class=AssetClass.COMMODITY,
        contract_size=Decimal("100"),
        pip_size=Decimal("0.01"),
        tick_size=Decimal("0.01"),
        min_lot=Decimal("0.01"),
        max_lot=Decimal("50"),
        lot_step=Decimal("0.01"),
        enable=True,
    )
    setattr(client, "_instruments_cache", {"XAUUSD": spec})
    setattr(
        client,
        "_instruments_cache_time",
        datetime.now(timezone.utc) - timedelta(seconds=350),
    )

    # REST endpoint returns valid fresh data
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "XAUUSD",
                "assetClass": "COMMODITY",
                "contractSize": "100",
                "tickSize": "0.01",
                "pipSize": "0.01",
                "minVolume": "0.01",
                "maxVolume": "50",
                "stepVolume": "0.01",
                "enable": "2",
            }
        ],
    }

    trading_engine = TradingEngine(
        risk_engine=RiskEngine(
            settings=RiskSettings(max_position_size_usdt=Decimal("100000"))
        ),
        portfolio_engine=PortfolioEngine(),
        cfd_sizing_engine=client.sizing,
        market_type=MarketType.CFD,
    )

    class _MockBalance:
        async def get_free_balance(self, *, asset: str) -> Decimal:
            del asset
            return Decimal("10000")

    class _MockPosition:
        async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
            del synchronize
            return ()

    service = LiveEntryRiskEvaluationService(
        account_service=_MockBalance(),
        position_service=_MockPosition(),
        trading_engine=trading_engine,
        balance_asset="USDT",
        instrument_refresher=client,
    )

    signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        price=Decimal("2600.00"),
        stop_loss=Decimal("2590.00"),
        take_profit=Decimal("2620.00"),
        confidence=Decimal("0.9"),
        strategy_name=StrategyType.EMA_CROSS.value,
        generated_at=datetime.now(timezone.utc),
    )

    # Evaluate
    evaluation = await service.evaluate(signal=signal)

    # The evaluation succeeded because metadata was refreshed
    assert evaluation.decision.should_execute is True
    assert evaluation.decision.risk_result is not None
    assert any(path == "/api/v3/cfd/account/instruments" for _, path in rest.history)


@pytest.mark.asyncio
async def test_live_entry_risk_evaluation_service_fails_closed_when_refresh_fails() -> (
    None
):
    """LiveEntryRiskEvaluationService fails closed when metadata refresh fails."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, is_live=True)

    # Expired cache
    setattr(client, "_instruments_cache", {})
    setattr(
        client,
        "_instruments_cache_time",
        datetime.now(timezone.utc) - timedelta(seconds=350),
    )

    # Refresh will fail with network error
    rest.canned_response = {
        "code": "50000",
        "msg": "Connection error",
        "data": [],
    }

    trading_engine = TradingEngine(
        risk_engine=RiskEngine(settings=RiskSettings()),
        portfolio_engine=PortfolioEngine(),
        cfd_sizing_engine=client.sizing,
        market_type=MarketType.CFD,
    )

    class _MockBalance:
        async def get_free_balance(self, *, asset: str) -> Decimal:
            del asset
            return Decimal("10000")

    class _MockPosition:
        async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
            del synchronize
            return ()

    service = LiveEntryRiskEvaluationService(
        account_service=_MockBalance(),
        position_service=_MockPosition(),
        trading_engine=trading_engine,
        balance_asset="USDT",
        instrument_refresher=client,
    )

    signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        price=Decimal("2600.00"),
        stop_loss=Decimal("2590.00"),
        take_profit=Decimal("2620.00"),
        confidence=Decimal("0.9"),
        strategy_name=StrategyType.EMA_CROSS.value,
        generated_at=datetime.now(timezone.utc),
    )

    # Evaluate
    evaluation = await service.evaluate(signal=signal)

    # Fails closed
    assert evaluation.decision.should_execute is False
    assert "Authoritative instrument metadata refresh failed" in (
        evaluation.decision.reason or ""
    )


# =============================================================================
# Close Positions Contract Regression Tests
# =============================================================================
@pytest.mark.asyncio
async def test_cfd_close_position_sends_only_supported_fields() -> None:
    """Verify close_position sends only positionId and qty, and handles data: null."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.positions_store = [
        {
            "symbol": "EURUSD",
            "posSide": "long",
            "positionId": "pos_cfd_123",
            "total": "1.5",
            "openPriceAvg": "1.0850",
            "markPrice": "1.0890",
            "unrealizedPl": "10.0",
            "leverage": "50",
            "uTime": "1700000000000",
        }
    ]
    rest.auto_reconcile_positions = True
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": None,
    }

    closed = await client.close_position(
        symbol="EURUSD",
        client_order_id="close_client_req_test",
        position_id="pos_cfd_123",
        quantity=Decimal("1.5"),
        initial_quantity=Decimal("1.5"),
        side=PositionSide.LONG,
        bypass_calendar_guard=True,
    )

    # 1. Request body contains only positionId and qty
    assert rest.last_post_path == "/api/v3/cfd/trade/close-positions"
    assert ("GET", "/api/v3/cfd/trade/current-positions") in rest.history
    assert rest.last_data == {
        "positionId": "pos_cfd_123",
        "qty": "1.5",
    }
    # 2. clientOid is NOT in request body
    assert "clientOid" not in (rest.last_data or {})

    # 3. data: null produces valid domain Order
    assert closed.symbol == "EURUSD"
    assert closed.side is OrderSide.SELL
    assert closed.order_type is OrderType.MARKET
    assert closed.status is OrderStatus.FILLED
    assert closed.quantity == Decimal("1.5")
    assert closed.executed_quantity == Decimal("1.5")
    assert closed.client_order_id == "close_client_req_test"

    # 9. No fake or synthetic orderId created
    assert closed.order_id == ""


@pytest.mark.asyncio
async def test_cfd_close_position_reconciliation_full_close_confirmed() -> None:
    """Verify data: null with position disappearing confirms full close."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.positions_store = [
        {
            "symbol": "EURUSD",
            "posSide": "long",
            "positionId": "pos_full_1",
            "total": "2.5",
            "openPriceAvg": "1.0800",
            "markPrice": "1.0850",
            "unrealizedPl": "50.0",
            "leverage": "50",
            "uTime": "1700000000000",
        }
    ]
    rest.auto_reconcile_positions = True
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": None,
    }

    closed = await client.close_position(
        symbol="EURUSD",
        position_id="pos_full_1",
        quantity=Decimal("2.5"),
        side=PositionSide.LONG,
        bypass_calendar_guard=True,
    )

    assert closed.status is OrderStatus.FILLED
    assert closed.quantity == Decimal("2.5")
    assert closed.executed_quantity == Decimal("2.5")
    assert closed.order_id == ""
    assert rest.positions_store == []


@pytest.mark.asyncio
async def test_cfd_close_position_reconciliation_partial_close_confirmed() -> None:
    """Verify data: null with matching remaining quantity confirms partial close."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.positions_store = [
        {
            "symbol": "EURUSD",
            "posSide": "long",
            "positionId": "pos_part_1",
            "total": "2.0",
            "openPriceAvg": "1.0800",
            "markPrice": "1.0850",
            "unrealizedPl": "50.0",
            "leverage": "50",
            "uTime": "1700000000000",
        }
    ]
    rest.auto_reconcile_positions = True
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": None,
    }

    # Close 0.5 of 2.0 -> expected remaining 1.5
    closed = await client.close_position(
        symbol="EURUSD",
        position_id="pos_part_1",
        quantity=Decimal("0.5"),
        initial_quantity=Decimal("2.0"),
        side=PositionSide.LONG,
        bypass_calendar_guard=True,
    )

    assert closed.status is OrderStatus.FILLED
    assert closed.quantity == Decimal("0.5")
    assert closed.executed_quantity == Decimal("0.5")
    assert closed.order_id == ""
    assert len(rest.positions_store) == 1
    assert rest.positions_store[0]["total"] == "1.5"


@pytest.mark.asyncio
async def test_cfd_close_position_reconciliation_unchanged_raises_unknown() -> None:
    """Verify data: null with unchanged position raises outcome unknown error."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(
        rest=rest,
        mapper=mapper,
        mode="ecn",
        close_reconciliation_attempts=2,
        close_reconciliation_delay_seconds=0.0,
    )

    # Position remains unchanged on server despite close call
    rest.positions_store = [
        {
            "symbol": "EURUSD",
            "posSide": "long",
            "positionId": "pos_unchanged_1",
            "total": "1.0",
            "openPriceAvg": "1.0800",
            "markPrice": "1.0850",
            "unrealizedPl": "10.0",
            "leverage": "50",
            "uTime": "1700000000000",
        }
    ]
    rest.auto_reconcile_positions = False
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": None,
    }

    with pytest.raises(
        ExchangeOrderOutcomeUnknownError, match="outcome could not be confirmed"
    ):
        await client.close_position(
            symbol="EURUSD",
            position_id="pos_unchanged_1",
            quantity=Decimal("1.0"),
            initial_quantity=Decimal("1.0"),
            side=PositionSide.LONG,
            bypass_calendar_guard=True,
        )


@pytest.mark.asyncio
async def test_cfd_close_position_partial_unexpected_raises_unknown() -> None:
    """Verify data: null with unexpected partial qty raises outcome unknown error."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(
        rest=rest,
        mapper=mapper,
        mode="ecn",
        close_reconciliation_attempts=2,
        close_reconciliation_delay_seconds=0.0,
    )

    # Initial 2.0, close 0.5 requested, but server reports remaining 1.8 (mismatch)
    rest.positions_store = [
        {
            "symbol": "EURUSD",
            "posSide": "long",
            "positionId": "pos_unexpected_1",
            "total": "1.8",
            "openPriceAvg": "1.0800",
            "markPrice": "1.0850",
            "unrealizedPl": "10.0",
            "leverage": "50",
            "uTime": "1700000000000",
        }
    ]
    rest.auto_reconcile_positions = False
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": None,
    }

    with pytest.raises(
        ExchangeOrderOutcomeUnknownError, match="outcome could not be confirmed"
    ):
        await client.close_position(
            symbol="EURUSD",
            position_id="pos_unexpected_1",
            quantity=Decimal("0.5"),
            initial_quantity=Decimal("2.0"),
            side=PositionSide.LONG,
            bypass_calendar_guard=True,
        )


@pytest.mark.asyncio
async def test_cfd_close_position_reconciliation_timeout_raises_unknown() -> None:
    """Verify reconciliation read failures raise ExchangeOrderOutcomeUnknownError."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(
        rest=rest,
        mapper=mapper,
        mode="ecn",
        close_reconciliation_attempts=2,
        close_reconciliation_delay_seconds=0.0,
    )

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": None,
    }

    async def _failing_get(path: str, *args: object, **kwargs: object) -> JsonResponse:
        del args, kwargs
        if path == "/api/v3/cfd/trade/current-positions":
            raise TimeoutError("Reconciliation read timed out")
        return {"code": "00000", "msg": "success", "data": None}

    setattr(rest, "get", _failing_get)

    with pytest.raises(
        ExchangeOrderOutcomeUnknownError, match="outcome could not be confirmed"
    ):
        await client.close_position(
            symbol="EURUSD",
            position_id="pos_read_timeout_1",
            quantity=Decimal("1.0"),
            initial_quantity=Decimal("1.0"),
            side=PositionSide.LONG,
            bypass_calendar_guard=True,
        )


@pytest.mark.asyncio
async def test_cfd_close_position_api_rejection_fails() -> None:
    """Verify API rejection raises ExchangeOrderRejectedError."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {
        "code": "40017",
        "msg": "position not exist",
        "data": None,
    }

    with pytest.raises(ExchangeOrderRejectedError, match="rejected"):
        await client.close_position(
            symbol="EURUSD",
            position_id="pos_cfd_nonexistent",
            quantity=Decimal("1.0"),
            initial_quantity=Decimal("1.0"),
            bypass_calendar_guard=True,
        )


@pytest.mark.asyncio
async def test_cfd_close_position_transport_failure_is_outcome_unknown() -> None:
    """Verify timeout and connection failures raise ExchangeOrderOutcomeUnknownError."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    async def _failing_post(*args: object, **kwargs: object) -> JsonResponse:
        del args, kwargs
        raise TimeoutError("Connection to Bitget CFD timed out")

    setattr(rest, "post", _failing_post)

    with pytest.raises(ExchangeOrderOutcomeUnknownError, match="outcome is unknown"):
        await client.close_position(
            symbol="EURUSD",
            position_id="pos_timeout_1",
            quantity=Decimal("1.0"),
            initial_quantity=Decimal("1.0"),
            bypass_calendar_guard=True,
        )


@pytest.mark.asyncio
async def test_cfd_close_position_exact_and_close_only_semantics() -> None:
    """Verify close_position_exact works with data: null and close-only instrument."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    spec_close_only = mapper.map_instrument_spec(
        {
            "symbol": "EURUSD",
            "contractSize": "100000",
            "tickSize": "0.00001",
            "pipSize": "0.0001",
            "minVolume": "0.01",
            "maxVolume": "100.0",
            "stepVolume": "0.01",
            "enable": "1",
        }
    )
    assert spec_close_only.is_close_only
    setattr(client, "_instruments_cache", {"EURUSD": spec_close_only})
    setattr(client, "_instruments_cache_time", datetime.now(timezone.utc))

    rest.positions_store = [
        {
            "symbol": "EURUSD",
            "posSide": "short",
            "positionId": "pos_cfd_close_only_exact",
            "total": "2.0",
            "openPriceAvg": "1.0850",
            "markPrice": "1.0820",
            "unrealizedPl": "60.0",
            "leverage": "50",
            "uTime": "1700000000000",
        }
    ]
    rest.auto_reconcile_positions = True
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": None,
    }

    now = datetime.now(timezone.utc)
    pos = Position(
        symbol="EURUSD",
        side=PositionSide.SHORT,
        quantity=Decimal("2.0"),
        entry_price=Decimal("1.0850"),
        current_price=Decimal("1.0820"),
        leverage=50,
        unrealized_pnl=Decimal("60.0"),
        opened_at=now,
        updated_at=now,
        position_id="pos_cfd_close_only_exact",
    )

    closed = await client.close_position_exact(
        position=pos,
        client_order_id="close_only_cl_id_99",
    )

    assert closed.order_id == ""
    assert closed.client_order_id == "close_only_cl_id_99"
    assert closed.side is OrderSide.BUY  # Closing SHORT is BUY
    assert closed.status is OrderStatus.FILLED
    assert rest.last_data == {
        "positionId": "pos_cfd_close_only_exact",
        "qty": "2.0",
    }
    assert "clientOid" not in (rest.last_data or {})
    assert rest.positions_store == []


@pytest.mark.asyncio
async def test_cfd_close_all_positions_with_data_null() -> None:
    """Verify close_all_positions succeeds for all positions with data: null."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.positions_store = [
        {
            "symbol": "EURUSD",
            "posSide": "long",
            "positionId": "pos-all-1",
            "total": "1.0",
            "openPriceAvg": "1.0850",
            "markPrice": "1.0890",
            "unrealizedPl": "40.0",
            "leverage": "50",
            "uTime": "1700000000000",
        },
        {
            "symbol": "GBPUSD",
            "posSide": "short",
            "positionId": "pos-all-2",
            "total": "2.0",
            "openPriceAvg": "1.2600",
            "markPrice": "1.2580",
            "unrealizedPl": "50.0",
            "leverage": "50",
            "uTime": "1700000000000",
        },
    ]
    rest.auto_reconcile_positions = True
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": None,
    }

    closed_orders = await client.close_all_positions()

    assert len(closed_orders) == 2
    assert closed_orders[0].symbol == "EURUSD"
    assert closed_orders[0].side is OrderSide.SELL
    assert closed_orders[0].status is OrderStatus.FILLED
    assert closed_orders[0].order_id == ""

    assert closed_orders[1].symbol == "GBPUSD"
    assert closed_orders[1].side is OrderSide.BUY
    assert closed_orders[1].status is OrderStatus.FILLED
    assert closed_orders[1].order_id == ""
    assert rest.positions_store == []
