"""Binance Futures V3 position leverage enrichment regressions."""

from __future__ import annotations

from decimal import Decimal

import pytest

from botragram.exchanges.base.rest import JsonResponse, QueryParams, RequestHeaders
from botragram.exchanges.binance import BinanceFuturesExchangeClient
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient

_POSITION_ENDPOINT = "/fapi/v3/positionRisk"
_SYMBOL_CONFIG_ENDPOINT = "/fapi/v1/symbolConfig"


class _PositionRestClient(BinanceRestClient):
    """Return V3 positions and their separate authoritative configuration."""

    __slots__ = ("leverage", "requests")

    def __init__(self, *, leverage: int) -> None:
        """Initialize deterministic position/configuration responses."""
        super().__init__(base_url="https://example.test")
        self.leverage = leverage
        self.requests: list[tuple[str, QueryParams | None, bool]] = []

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Return one active V3 position or its symbol configuration."""
        del headers
        self.requests.append((path, params, authenticated))
        if path == _POSITION_ENDPOINT:
            return [
                {
                    "symbol": "BTCUSDT",
                    "positionAmt": "0.01",
                    "entryPrice": "60000",
                    "markPrice": "60100",
                    "unRealizedProfit": "1",
                    "positionSide": "BOTH",
                    "updateTime": 1_700_000_000_000,
                }
            ]
        if path == _SYMBOL_CONFIG_ENDPOINT:
            return [
                {
                    "symbol": "BTCUSDT",
                    "leverage": self.leverage,
                }
            ]
        raise AssertionError(f"Unexpected GET path: {path}")


@pytest.mark.asyncio
async def test_positions_resolve_leverage_from_symbol_config() -> None:
    """V3 position state must not fabricate zero when leverage moved endpoints."""
    rest = _PositionRestClient(leverage=7)
    client = BinanceFuturesExchangeClient(
        rest=rest,
        mapper=BinanceExchangeMapper(),
    )

    positions = await client.get_positions(symbol="btcusdt")

    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].quantity == Decimal("0.01")
    assert positions[0].leverage == 7
    assert rest.requests == [
        (_POSITION_ENDPOINT, {"symbol": "BTCUSDT"}, True),
        (_SYMBOL_CONFIG_ENDPOINT, {"symbol": "BTCUSDT"}, True),
    ]


@pytest.mark.asyncio
async def test_positions_reject_invalid_symbol_config_leverage() -> None:
    """Do not report a fabricated leverage when venue configuration is invalid."""
    client = BinanceFuturesExchangeClient(
        rest=_PositionRestClient(leverage=0),
        mapper=BinanceExchangeMapper(),
    )

    with pytest.raises(RuntimeError, match="symbol leverage is invalid"):
        await client.get_positions(symbol="BTCUSDT")
