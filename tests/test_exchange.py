"""
Botragram

Description:
    Exchange factory and Binance payload mapping tests.

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
from datetime import timezone
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
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.exchanges.binance.client import BinanceExchangeClient
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.exchanges.binance.stream import BinanceStreamClient
from botragram.exchanges.factory import ExchangeFactory


# =============================================================================
# Factory Tests
# =============================================================================
def test_exchange_factory_builds_matching_binance_dependencies() -> None:
    """Verify factory creates one matching Binance client pair."""
    exchange_client, stream_client = ExchangeFactory.create(
        exchange_type=ExchangeType.BINANCE,
        rest_base_url="https://example.test",
        websocket_base_url="wss://example.test",
    )

    assert isinstance(exchange_client, BinanceExchangeClient)
    assert isinstance(stream_client, BinanceStreamClient)


@pytest.mark.parametrize(
    "exchange_type",
    (ExchangeType.BITGET, ExchangeType.BYBIT, ExchangeType.OKX),
)
def test_exchange_factory_rejects_unimplemented_exchange_types(
    exchange_type: ExchangeType,
) -> None:
    """Verify incomplete exchange integrations cannot be selected silently."""
    with pytest.raises(ValueError, match="Unsupported exchange type"):
        ExchangeFactory.create_rest_client(
            exchange_type=exchange_type,
            base_url="https://example.test",
        )


def test_exchange_factory_accepts_a_binance_transport_subclass() -> None:
    """Verify compatible Binance transport extensions preserve the contract."""

    class OtherRestClient(BinanceRestClient):
        """Test transport used to retain the required abstract contract."""

    rest_client = OtherRestClient(base_url="https://example.test")

    assert isinstance(
        ExchangeFactory.create_exchange_client(
            exchange_type=ExchangeType.BINANCE,
            rest_client=rest_client,
        ),
        BinanceExchangeClient,
    )


# =============================================================================
# Mapper Tests
# =============================================================================
def test_binance_mapper_maps_account_and_balances() -> None:
    """Verify account capabilities and Decimal balances are normalized."""
    account = BinanceExchangeMapper().map_account(
        {
            "canTrade": True,
            "canDeposit": "true",
            "canWithdraw": 1,
            "balances": [
                {
                    "asset": "USDT",
                    "free": "100.25",
                    "locked": "2.5",
                }
            ],
        }
    )

    assert account.can_trade
    assert account.can_deposit
    assert account.can_withdraw
    assert len(account.balances) == 1
    assert account.balances[0].asset == "USDT"
    assert account.balances[0].free == Decimal("100.25")
    assert account.balances[0].locked == Decimal("2.5")


def test_binance_mapper_maps_rest_ticker_and_candle() -> None:
    """Verify REST market payloads become timezone-aware domain models."""
    mapper = BinanceExchangeMapper()
    ticker = mapper.map_ticker(
        {
            "symbol": "BTCUSDT",
            "bidPrice": "99.5",
            "askPrice": "100.5",
            "lastPrice": "100",
            "closeTime": 1_700_000_000_000,
        }
    )
    candle = mapper.map_candle(
        [
            1_700_000_000_000,
            "99",
            "102",
            "98",
            "101",
            "12.5",
            1_700_000_060_000,
        ],
        symbol="BTCUSDT",
        interval=Interval.M1,
    )

    assert ticker.symbol == "BTCUSDT"
    assert ticker.bid_price == Decimal("99.5")
    assert ticker.timestamp.tzinfo is timezone.utc
    assert candle.interval is Interval.M1
    assert candle.open_price == Decimal("99")
    assert candle.close_price == Decimal("101")
    assert candle.close_time.tzinfo is timezone.utc


def test_binance_mapper_maps_optional_order_prices() -> None:
    """Verify zero or absent Binance order prices remain optional."""
    order = BinanceExchangeMapper().map_order(
        {
            "orderId": 123,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "status": "FILLED",
            "origQty": "1.2",
            "executedQty": "1.2",
            "price": "0",
            "stopPrice": "",
            "transactTime": 1_700_000_000_000,
        }
    )

    assert order.order_id == "123"
    assert order.side is OrderSide.BUY
    assert order.order_type is OrderType.MARKET
    assert order.status is OrderStatus.FILLED
    assert order.price is None
    assert order.stop_price is None


def test_binance_mapper_maps_short_position_and_trade_fallbacks() -> None:
    """Verify signed positions and buyer flags map to domain enum values."""
    mapper = BinanceExchangeMapper()
    position = mapper.map_position(
        {
            "symbol": "BTCUSDT",
            "positionSide": "BOTH",
            "positionAmt": "-2",
            "entryPrice": "100",
            "markPrice": "90",
            "unRealizedProfit": "20",
            "leverage": "3",
            "updateTime": 1_700_000_000_000,
        }
    )
    trade = mapper.map_trade(
        {
            "id": 5,
            "orderId": 7,
            "symbol": "BTCUSDT",
            "isBuyer": False,
            "price": "100",
            "qty": "2",
            "commission": "0.1",
            "commissionAsset": "USDT",
            "time": 1_700_000_000_000,
        }
    )

    assert position.side is PositionSide.SHORT
    assert position.quantity == Decimal("2")
    assert trade.side is OrderSide.SELL
    assert trade.quote_quantity == Decimal("200")


def test_binance_mapper_rejects_malformed_payloads() -> None:
    """Verify malformed vendor payloads fail at the exchange boundary."""
    mapper = BinanceExchangeMapper()

    with pytest.raises(ValueError, match="at least 7 elements"):
        mapper.map_candle(
            [1, "1"],
            symbol="BTCUSDT",
            interval=Interval.M1,
        )

    with pytest.raises(ValueError, match="balances"):
        mapper.map_account({"balances": {}})
