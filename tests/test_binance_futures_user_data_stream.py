"""Binance Futures private User Data Stream payload mapping tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from botragram.enums import OrderSide, OrderStatus, OrderType
from botragram.exchanges.binance.futures_user_data_stream import (
    BinanceFuturesUserDataStream,
)
from botragram.models import FuturesUserDataAccountUpdate, FuturesUserDataOrderUpdate

_TIMESTAMP_MS = 1_756_080_000_000
_OBSERVED_AT = datetime.fromtimestamp(_TIMESTAMP_MS / 1_000, tz=UTC)


def test_maps_account_update_balance_and_position() -> None:
    """Map private account updates without exposing Binance payload mappings."""
    event = BinanceFuturesUserDataStream.map_account_update(
        payload={
            "E": _TIMESTAMP_MS,
            "a": {
                "B": [{"a": "USDT", "cw": "125.50"}],
                "P": [
                    {
                        "s": "BTCUSDT",
                        "pa": "0.25",
                        "ep": "100000",
                        "up": "12.5",
                    }
                ],
            },
        }
    )

    assert isinstance(event, FuturesUserDataAccountUpdate)
    assert event.observed_at == _OBSERVED_AT
    assert event.balances[0].free == Decimal("125.50")
    assert event.positions[0].symbol == "BTCUSDT"
    assert event.positions[0].quantity == Decimal("0.25")


def test_maps_order_trade_update_to_existing_order_model() -> None:
    """Map private order status updates to the immutable common Order model."""
    event = BinanceFuturesUserDataStream.map_order_update(
        payload={
            "E": _TIMESTAMP_MS,
            "o": {
                "i": 12345,
                "s": "BTCUSDT",
                "S": "SELL",
                "o": "STOP_MARKET",
                "X": "NEW",
                "q": "0.25",
                "z": "0",
                "p": "0",
                "sp": "95000",
                "T": _TIMESTAMP_MS,
                "c": "bsl-0123456789abcdef0123456789abcdef",
            },
        }
    )

    assert isinstance(event, FuturesUserDataOrderUpdate)
    assert event.order.order_id == "12345"
    assert event.order.side is OrderSide.SELL
    assert event.order.order_type is OrderType.STOP_MARKET
    assert event.order.status is OrderStatus.NEW
    assert event.order.stop_price == Decimal("95000")
