"""
Botragram

Description:
    Unit tests for Fase 2 Trailing Stop based on Confirmed Swing Pivots.

Python:
    3.14+
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import create_autospec

import pytest

from botragram.engine.risk_engine import RiskEngine
from botragram.enums import Interval, PositionSide, TradeMode, TrailingMode
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Candle, Position, Ticker
from botragram.services.position_protection_manager import PositionProtectionManager
from botragram.storage.memory.candle_repository import MemoryCandleRepository
from botragram.storage.memory.position_repository import MemoryPositionRepository

_NOW = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)


def _make_candle(
    *,
    index: int,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
) -> Candle:
    open_time = _NOW + timedelta(minutes=5 * index)
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M5,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=5),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=Decimal("100.0"),
    )


def test_swing_pivot_requires_minimum_candles() -> None:
    """Return None when candle count is less than window."""
    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("105.0"),
        unrealized_pnl=Decimal("5.0"),
        leverage=3,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95.0"),
        take_profit=Decimal("120.0"),
    )
    candles = [
        _make_candle(
            index=i,
            open_price=Decimal("100"),
            high_price=Decimal("102"),
            low_price=Decimal("99"),
            close_price=Decimal("101"),
        )
        for i in range(4)
    ]
    res = RiskEngine.calculate_swing_pivot_stop_loss(
        position=pos,
        candles=candles,
        window=5,
    )
    assert res is None


def test_swing_pivot_confirmed_higher_low_long() -> None:
    """Calculate tighter SL below a confirmed 5-bar Higher Low for LONG."""
    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("108.0"),
        unrealized_pnl=Decimal("8.0"),
        leverage=3,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("96.0"),
        take_profit=Decimal("120.0"),
    )

    # 7 candles with a valley (Higher Low) at candle index 4 (low=102.0)
    # Candle 2 (left 2): low=104.0
    # Candle 3 (left 1): low=103.0
    # Candle 4 (center): low=102.0 (< 104 and < 103)
    # Candle 5 (right 1): low=103.5 (>= 102.0)
    # Candle 6 (right 2): low=105.0 (>= 102.0)
    candles = [
        _make_candle(
            index=0,
            open_price=Decimal("100"),
            high_price=Decimal("102"),
            low_price=Decimal("99"),
            close_price=Decimal("101"),
        ),
        _make_candle(
            index=1,
            open_price=Decimal("101"),
            high_price=Decimal("103"),
            low_price=Decimal("100"),
            close_price=Decimal("102"),
        ),
        _make_candle(
            index=2,
            open_price=Decimal("102"),
            high_price=Decimal("105"),
            low_price=Decimal("104"),
            close_price=Decimal("104.5"),
        ),
        _make_candle(
            index=3,
            open_price=Decimal("104.5"),
            high_price=Decimal("104.8"),
            low_price=Decimal("103.0"),
            close_price=Decimal("103.2"),
        ),
        _make_candle(
            index=4,
            open_price=Decimal("103.2"),
            high_price=Decimal("103.5"),
            low_price=Decimal("102.0"),  # Valley / Swing Low
            close_price=Decimal("102.8"),
        ),
        _make_candle(
            index=5,
            open_price=Decimal("102.8"),
            high_price=Decimal("106.0"),
            low_price=Decimal("102.5"),  # Confirms right 1
            close_price=Decimal("105.5"),
        ),
        _make_candle(
            index=6,
            open_price=Decimal("105.5"),
            high_price=Decimal("108.5"),
            low_price=Decimal("105.0"),  # Confirms right 2
            close_price=Decimal("108.0"),
        ),
    ]

    new_sl = RiskEngine.calculate_swing_pivot_stop_loss(
        position=pos,
        candles=candles,
        window=5,
        buffer_pct=Decimal("0.0015"),
    )
    assert new_sl is not None
    expected = Decimal("102.0") * (Decimal("1") - Decimal("0.0015"))
    assert new_sl == expected
    assert pos.stop_loss is not None
    assert new_sl > pos.stop_loss
    assert new_sl < candles[-1].close_price


def test_swing_pivot_short_lowers_stop_loss() -> None:
    """Calculate tighter SL above a confirmed 5-bar Lower High for SHORT."""
    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.SHORT,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("92.0"),
        unrealized_pnl=Decimal("8.0"),
        leverage=3,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("104.0"),
        take_profit=Decimal("80.0"),
    )

    # Peak at candle index 2 with high=96.0
    candles = [
        _make_candle(
            index=0,
            open_price=Decimal("94"),
            high_price=Decimal("95.0"),
            low_price=Decimal("93.0"),
            close_price=Decimal("94.5"),
        ),
        _make_candle(
            index=1,
            open_price=Decimal("94.5"),
            high_price=Decimal("95.5"),
            low_price=Decimal("94.0"),
            close_price=Decimal("95.0"),
        ),
        _make_candle(
            index=2,
            open_price=Decimal("95.0"),
            high_price=Decimal("96.0"),  # Lower High Peak
            low_price=Decimal("94.0"),
            close_price=Decimal("94.8"),
        ),
        _make_candle(
            index=3,
            open_price=Decimal("94.8"),
            high_price=Decimal("95.2"),  # Right 1 confirmation
            low_price=Decimal("93.0"),
            close_price=Decimal("93.5"),
        ),
        _make_candle(
            index=4,
            open_price=Decimal("93.5"),
            high_price=Decimal("94.0"),  # Right 2 confirmation
            low_price=Decimal("91.5"),
            close_price=Decimal("92.0"),
        ),
    ]

    new_sl = RiskEngine.calculate_swing_pivot_stop_loss(
        position=pos,
        candles=candles,
        window=5,
        buffer_pct=Decimal("0.0015"),
    )
    assert new_sl is not None
    expected = Decimal("96.0") * (Decimal("1") + Decimal("0.0015"))
    assert new_sl == expected
    assert pos.stop_loss is not None
    assert new_sl < pos.stop_loss
    assert new_sl > candles[-1].close_price


@pytest.mark.asyncio
async def test_position_protection_manager_swing_pivot_mode() -> None:
    """PositionProtectionManager advances SL on Higher Low in SWING_PIVOT mode."""
    pos_repo = MemoryPositionRepository()
    candle_repo = MemoryCandleRepository()

    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("108.0"),
        unrealized_pnl=Decimal("8.0"),
        leverage=3,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("96.0"),
        take_profit=Decimal("120.0"),
        protection_step=0,
    )
    await pos_repo.save(position=pos)

    # Add 5-bar confirmed higher low candles
    candles = [
        _make_candle(
            index=0,
            open_price=Decimal("100"),
            high_price=Decimal("102"),
            low_price=Decimal("99"),
            close_price=Decimal("101"),
        ),
        _make_candle(
            index=1,
            open_price=Decimal("101"),
            high_price=Decimal("103"),
            low_price=Decimal("100"),
            close_price=Decimal("102"),
        ),
        _make_candle(
            index=2,
            open_price=Decimal("102"),
            high_price=Decimal("105"),
            low_price=Decimal("104"),
            close_price=Decimal("104.5"),
        ),
        _make_candle(
            index=3,
            open_price=Decimal("104.5"),
            high_price=Decimal("104.8"),
            low_price=Decimal("103.0"),
            close_price=Decimal("103.2"),
        ),
        _make_candle(
            index=4,
            open_price=Decimal("103.2"),
            high_price=Decimal("103.5"),
            low_price=Decimal("102.0"),  # Higher low
            close_price=Decimal("102.8"),
        ),
        _make_candle(
            index=5,
            open_price=Decimal("102.8"),
            high_price=Decimal("106.0"),
            low_price=Decimal("102.5"),
            close_price=Decimal("105.5"),
        ),
        _make_candle(
            index=6,
            open_price=Decimal("105.5"),
            high_price=Decimal("108.5"),
            low_price=Decimal("105.0"),
            close_price=Decimal("108.0"),
        ),
    ]
    await candle_repo.save_many(candles=candles)

    mock_exchange = create_autospec(BaseExchangeClient, instance=True)
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=pos_repo,
        exchange_client=mock_exchange,
        trailing_mode=TrailingMode.SWING_PIVOT,
        trailing_swing_timeframe=Interval.M5,
        trailing_swing_window=5,
        trailing_buffer_pct=Decimal("0.0015"),
        candle_repository=candle_repo,
    )

    ticker = Ticker(
        symbol="BTCUSDT",
        bid_price=Decimal("107.9"),
        ask_price=Decimal("108.1"),
        last_price=Decimal("108.0"),
        timestamp=_NOW + timedelta(minutes=35),
    )
    await manager.on_market_tick(ticker=ticker)

    updated = await pos_repo.get_by_symbol(symbol="BTCUSDT")
    assert updated is not None
    assert updated.protection_step == 1
    expected_sl = Decimal("102.0") * (Decimal("1") - Decimal("0.0015"))
    assert updated.stop_loss == expected_sl


@pytest.mark.asyncio
async def test_position_protection_manager_swing_pivot_breakeven_floor() -> None:
    """SWING_PIVOT mode enforces Breakeven floor when swing pivot is below entry."""
    pos_repo = MemoryPositionRepository()
    candle_repo = MemoryCandleRepository()

    # Entry 100.0, TP 120.0, SL 95.0. Current 108.0 (progress = 40% >= 35% breakeven)
    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("108.0"),
        unrealized_pnl=Decimal("8.0"),
        leverage=3,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95.0"),
        take_profit=Decimal("120.0"),
        protection_step=0,
    )
    await pos_repo.save(position=pos)

    # Swing low is at 98.0 (below entry 100.0)
    candles = [
        _make_candle(
            index=0,
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100"),
        ),
        _make_candle(
            index=1,
            open_price=Decimal("100"),
            high_price=Decimal("100.5"),
            low_price=Decimal("99.5"),
            close_price=Decimal("100"),
        ),
        _make_candle(
            index=2,
            open_price=Decimal("100"),
            high_price=Decimal("100.5"),
            low_price=Decimal("98.0"),  # Swing low below entry
            close_price=Decimal("99.5"),
        ),
        _make_candle(
            index=3,
            open_price=Decimal("99.5"),
            high_price=Decimal("102.0"),
            low_price=Decimal("99.0"),
            close_price=Decimal("101.5"),
        ),
        _make_candle(
            index=4,
            open_price=Decimal("101.5"),
            high_price=Decimal("105.0"),
            low_price=Decimal("101.0"),
            close_price=Decimal("104.5"),
        ),
        _make_candle(
            index=5,
            open_price=Decimal("104.5"),
            high_price=Decimal("108.5"),
            low_price=Decimal("104.0"),
            close_price=Decimal("108.0"),
        ),
    ]
    await candle_repo.save_many(candles=candles)

    mock_exchange = create_autospec(BaseExchangeClient, instance=True)
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=pos_repo,
        exchange_client=mock_exchange,
        trailing_mode=TrailingMode.SWING_PIVOT,
        trailing_swing_timeframe=Interval.M5,
        trailing_swing_window=5,
        trailing_buffer_pct=Decimal("0.0015"),
        breakeven_progress_threshold=Decimal("0.35"),
        breakeven_fee_buffer=Decimal("0.0010"),
        candle_repository=candle_repo,
    )

    ticker = Ticker(
        symbol="BTCUSDT",
        bid_price=Decimal("107.9"),
        ask_price=Decimal("108.1"),
        last_price=Decimal("108.0"),
        timestamp=_NOW + timedelta(minutes=30),
    )
    await manager.on_market_tick(ticker=ticker)

    updated = await pos_repo.get_by_symbol(symbol="BTCUSDT")
    assert updated is not None
    assert updated.protection_step >= 1
    # Breakeven floor is entry_price * (1 + fee_buffer) = 100.0 * 1.0010 = 100.1
    # Swing low would have been 98.0 * (1 - 0.0015) = 97.853 < 100.1
    expected_be_floor = Decimal("100.0") * (Decimal("1") + Decimal("0.0010"))
    assert updated.stop_loss == expected_be_floor


@pytest.mark.asyncio
async def test_position_protection_manager_swing_pivot_fallback_stepped() -> None:
    """SWING_PIVOT falls back to stepped_stop when candle data is unavailable."""
    pos_repo = MemoryPositionRepository()
    candle_repo = MemoryCandleRepository()  # Empty candles

    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("108.0"),
        unrealized_pnl=Decimal("8.0"),
        leverage=3,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("95.0"),
        take_profit=Decimal("120.0"),
        protection_step=0,
    )
    await pos_repo.save(position=pos)

    mock_exchange = create_autospec(BaseExchangeClient, instance=True)
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=pos_repo,
        exchange_client=mock_exchange,
        trailing_mode=TrailingMode.SWING_PIVOT,
        trailing_swing_timeframe=Interval.M3,
        candle_repository=candle_repo,
    )

    ticker = Ticker(
        symbol="BTCUSDT",
        bid_price=Decimal("107.9"),
        ask_price=Decimal("108.1"),
        last_price=Decimal("108.0"),
        timestamp=_NOW + timedelta(minutes=30),
    )
    await manager.on_market_tick(ticker=ticker)

    updated = await pos_repo.get_by_symbol(symbol="BTCUSDT")
    assert updated is not None
    # Stepped stop should have advanced the stop to step 2 (102.0)
    assert updated.protection_step == 2
    assert updated.stop_loss == Decimal("102.0")
