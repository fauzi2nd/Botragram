"""
Botragram

Description:
    Unit and regression tests for Phase 3: Exchange Abstraction & Precision.
    Covers CFD candle resampling, get_trades, and position close disambiguation.

Python:
    3.14+
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from botragram.enums import (
    Interval,
    OrderSide,
    PositionSide,
)
from botragram.exchanges.base.rest import JsonResponse, QueryParams, RequestHeaders
from botragram.exchanges.bitget import (
    BitgetCfdExchangeClient,
    BitgetCfdMapper,
    BitgetRestClient,
)


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
        data: dict[str, object] | None = None,
        params: QueryParams | None = None,
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
            return self._validate_response_envelope(self.canned_responses.pop(0))
        return self._validate_response_envelope(self.canned_response)


@pytest.mark.asyncio
async def test_bitget_cfd_supported_intervals() -> None:
    """Verify that Bitget CFD only declares its native intervals."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    assert Interval.M1 in client.supported_intervals
    assert Interval.M15 in client.supported_intervals
    assert Interval.H1 in client.supported_intervals
    assert Interval.H4 in client.supported_intervals
    assert Interval.D1 in client.supported_intervals

    assert Interval.M5 not in client.supported_intervals
    assert Interval.M3 not in client.supported_intervals
    assert Interval.M30 not in client.supported_intervals
    assert Interval.H2 not in client.supported_intervals


@pytest.mark.asyncio
async def test_bitget_cfd_resampling_non_native_m5() -> None:
    """Verify get_candles fetches 1m candles and resamples when 5m is requested."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    # Generate 10 consecutive 1-minute bars aligned to 5m boundary
    # 00:00 to 00:09 -> forms two 5m bars (00:00-00:05 and 00:05-00:10)
    base_epoch = 1700000000 - (1700000000 % 300)
    raw_1m_data: list[list[str]] = []
    for i in range(10):
        ts = (base_epoch + i * 60) * 1000
        raw_1m_data.append([str(ts), "100.0", "105.0", "95.0", "102.0", "10.0"])

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": raw_1m_data,
    }

    candles = await client.get_candles(
        symbol="XAUUSD",
        interval=Interval.M5,
        limit=2,
    )

    # Verify query used 1m native interval
    assert rest.last_params is not None
    assert rest.last_params.get("interval") == "1m"

    # Verify returned candles are 5m
    assert len(candles) == 2
    for c in candles:
        assert c.interval is Interval.M5
        assert c.symbol == "XAUUSD"


@pytest.mark.asyncio
async def test_bitget_cfd_get_trades() -> None:
    """Verify get_trades queries _CFD_TRADES_ENDPOINT and maps Trade models."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")

    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "list": [
                {
                    "tradeId": "trade_101",
                    "orderId": "order_cfd_1",
                    "symbol": "XAUUSD",
                    "side": "buy",
                    "price": "2650.50",
                    "size": "0.1",
                    "fee": "0.05",
                    "cTime": "1700000000000",
                }
            ]
        },
    }

    trades = await client.get_trades(symbol="XAUUSD", limit=10)
    assert len(trades) == 1
    t = trades[0]
    assert t.trade_id == "trade_101"
    assert t.order_id == "order_cfd_1"
    assert t.symbol == "XAUUSD"
    assert t.side is OrderSide.BUY
    assert t.price == Decimal("2650.50")
    assert t.quantity == Decimal("0.1")
    assert rest.last_path == "/api/v3/cfd/trade/history-order"


@pytest.mark.asyncio
async def test_bitget_cfd_close_position_side_disambiguation() -> None:
    """Verify CFD close_position supports side disambiguation."""
    rest = MockBitgetRestClient()
    mapper = BitgetCfdMapper()
    client = BitgetCfdExchangeClient(rest=rest, mapper=mapper, mode="ecn")
    # When side is None and multiple positions exist, raises RuntimeError
    rest.canned_response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "XAUUSD",
                "posSide": "long",
                "positionId": "pos_long_123",
                "size": "1.0",
                "openPrice": "2650.0",
            },
            {
                "symbol": "XAUUSD",
                "posSide": "short",
                "positionId": "pos_short_456",
                "size": "1.0",
                "openPrice": "2650.0",
            },
        ],
    }

    with pytest.raises(RuntimeError, match="Multiple active CFD positions"):
        await client.close_position(symbol="XAUUSD", bypass_calendar_guard=True)

    # When side is specified, resolves positionId and qty, then closes
    rest.canned_responses = [
        {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "symbol": "XAUUSD",
                    "posSide": "long",
                    "positionId": "pos_long_123",
                    "size": "1.0",
                    "openPrice": "2650.0",
                },
                {
                    "symbol": "XAUUSD",
                    "posSide": "short",
                    "positionId": "pos_short_456",
                    "size": "1.0",
                    "openPrice": "2650.0",
                },
            ],
        },
        {
            "code": "00000",
            "msg": "success",
            "data": {
                "orderId": "close_order_123",
                "symbol": "XAUUSD",
                "side": "sell",
                "status": "closed",
            },
        },
    ]

    order = await client.close_position(
        symbol="XAUUSD",
        side=PositionSide.LONG,
        bypass_calendar_guard=True,
    )
    assert order.order_id == "close_order_123"
    assert rest.last_data is not None
    assert rest.last_data.get("positionId") == "pos_long_123"
    assert rest.last_data.get("qty") == "1.0"
