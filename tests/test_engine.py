"""
Botragram

Description:
    Unit tests for core trading engine and sub-engines.

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
from botragram.engine.pnl_engine import PnLEngine
from botragram.engine.position_engine import PositionEngine
from botragram.engine.risk_engine import RiskEngine
from botragram.engine.signal_engine import SignalEngine
from botragram.engine.trading_engine import TradingEngine
from botragram.enums.interval import Interval
from botragram.enums.order_side import OrderSide
from botragram.enums.order_status import OrderStatus
from botragram.enums.order_type import OrderType
from botragram.enums.position_side import PositionSide
from botragram.enums.signal_type import SignalType
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.base.mapper import Candle, OrderResult, PositionInfo, Ticker
from botragram.strategies.ema_cross import EMACrossStrategy


# =============================================================================
# Mock Exchange Client for Testing
# =============================================================================
class MockExchangeClient(BaseExchangeClient):
    """Mock exchange client for offline deterministic unit testing."""

    async def fetch_ticker(self, symbol: str) -> Ticker:
        return Ticker(
            symbol=symbol,
            last_price=Decimal("50000.0"),
            bid_price=Decimal("49999.0"),
            ask_price=Decimal("50001.0"),
            volume_24h=Decimal("100.0"),
        )

    async def fetch_candles(
        self,
        symbol: str,
        interval: Interval,
        limit: int = 100,
    ) -> list[Candle]:
        return [
            Candle(
                timestamp_ms=i * 60000,
                open_price=Decimal("50000.0"),
                high_price=Decimal("50100.0"),
                low_price=Decimal("49900.0"),
                close_price=Decimal("50050.0"),
                volume=Decimal("10.0"),
            )
            for i in range(limit)
        ]

    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> OrderResult:
        return OrderResult(
            order_id="mock_order_123",
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=OrderStatus.NEW,
            price=price or Decimal("50000.0"),
            quantity=quantity,
            filled_quantity=Decimal("0"),
            average_price=Decimal("0"),
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        return True

    async def fetch_positions(
        self,
        symbol: str | None = None,
    ) -> list[PositionInfo]:
        return []

    async def close(self) -> None:
        pass


# =============================================================================
# Unit Tests
# =============================================================================
def test_pnl_engine() -> None:
    """Test PnLEngine calculations."""
    pnl = PnLEngine()
    unrealized = pnl.calculate_unrealized_pnl(
        entry_price=Decimal("50000"),
        mark_price=Decimal("55000"),
        quantity=Decimal("1.0"),
        side=PositionSide.LONG,
    )
    assert unrealized == Decimal("5000")

    realized = pnl.calculate_realized_pnl(
        entry_price=Decimal("50000"),
        exit_price=Decimal("52000"),
        quantity=Decimal("1.0"),
        side=PositionSide.LONG,
        fee=Decimal("10"),
    )
    assert realized == Decimal("1990")


def test_position_engine() -> None:
    """Test PositionEngine state tracking."""
    pos_engine = PositionEngine()
    pos = PositionInfo(
        symbol="BTCUSDT",
        position_side=PositionSide.LONG,
        size=Decimal("0.5"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("51000"),
        unrealized_pnl=Decimal("500"),
        leverage=10,
    )
    pos_engine.update_position(pos)
    assert pos_engine.has_active_position("BTCUSDT") is True
    assert pos_engine.get_position("BTCUSDT") == pos

    # Update size to 0 to simulate close
    closed_pos = PositionInfo(
        symbol="BTCUSDT",
        position_side=PositionSide.LONG,
        size=Decimal("0"),
        entry_price=Decimal("0"),
        mark_price=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        leverage=10,
    )
    pos_engine.update_position(closed_pos)
    assert pos_engine.has_active_position("BTCUSDT") is False


def test_risk_engine() -> None:
    """Test RiskEngine position sizing and validation."""
    risk = RiskEngine()
    qty = risk.calculate_position_size(
        account_balance=Decimal("10000"),
        entry_price=Decimal("50000"),
    )
    assert qty > Decimal("0")

    sl, tp = risk.calculate_sl_tp_prices(
        entry_price=Decimal("50000"), side=OrderSide.BUY
    )
    assert sl < Decimal("50000")
    assert tp > Decimal("50000")

    valid = risk.validate_order(quantity=Decimal("0.01"), entry_price=Decimal("50000"))
    assert valid is True


def test_signal_engine() -> None:
    """Test SignalEngine evaluation."""
    strat = EMACrossStrategy(fast_period=3, slow_period=5)
    sig_engine = SignalEngine(strategy=strat)
    candles = [
        Candle(
            timestamp_ms=i * 60000,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("100"),
            volume=Decimal("10"),
        )
        for i in range(10)
    ]
    signal = sig_engine.evaluate(candles)
    assert signal == SignalType.NEUTRAL


def test_trading_engine_lifecycle() -> None:
    """Test TradingEngine start/stop lifecycle with mock client."""

    async def run_test() -> None:
        mock_client = MockExchangeClient()
        engine = TradingEngine(exchange_client=mock_client)
        await engine.start()
        assert engine.is_running is True
        await engine.process_tick()
        await engine.stop()
        assert engine.is_running is False

    asyncio.run(run_test())
