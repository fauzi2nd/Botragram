"""
Botragram

Description:
    Unit tests for exchange connectors and mappers.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
import asyncio
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.order_side import OrderSide
from botragram.enums.order_type import OrderType
from botragram.exchanges.binance.client import BinanceClient
from botragram.exchanges.binance.mapper import BinanceMapper
from botragram.exchanges.bybit.client import BybitClient
from botragram.exchanges.bybit.mapper import BybitMapper


def test_bybit_mapper_candle() -> None:
    """Test Bybit candle mapping."""
    mapper = BybitMapper()
    raw = [1600000000000, "50000.5", "51000.0", "49500.0", "50500.0", "100.5", "5000"]
    candle = mapper.parse_candle(raw)
    assert candle.timestamp_ms == 1600000000000
    assert candle.open_price == Decimal("50000.5")
    assert candle.high_price == Decimal("51000.0")
    assert candle.low_price == Decimal("49500.0")
    assert candle.close_price == Decimal("50500.0")
    assert candle.volume == Decimal("100.5")


def test_binance_mapper_candle() -> None:
    """Test Binance candle mapping."""
    mapper = BinanceMapper()
    raw = [1600000000000, "60000.0", "61000.0", "59000.0", "60500.0", "200.0"]
    candle = mapper.parse_candle(raw)
    assert candle.timestamp_ms == 1600000000000
    assert candle.open_price == Decimal("60000.0")
    assert candle.close_price == Decimal("60500.0")


def test_bybit_client_order() -> None:
    """Test Bybit client order creation stub."""

    async def run_test() -> None:
        client = BybitClient(testnet=True)
        res = await client.create_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.01"),
        )
        assert res.symbol == "BTCUSDT"
        assert res.side == OrderSide.BUY
        await client.close()

    asyncio.run(run_test())


def test_binance_client_order() -> None:
    """Test Binance client order creation stub."""

    async def run_test() -> None:
        client = BinanceClient(testnet=True)
        res = await client.create_order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.05"),
            price=Decimal("65000.0"),
        )
        assert res.symbol == "BTCUSDT"
        assert res.side == OrderSide.SELL
        await client.close()

    asyncio.run(run_test())
