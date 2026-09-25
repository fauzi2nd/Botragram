"""
Botragram

Description:
    Unit tests for PositionExitEngine and PositionExitService.

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
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine.position_exit_engine import PositionExitEngine
from botragram.enums import (
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionExitAction,
    PositionSide,
    SignalType,
    TradeMode,
)
from botragram.models import (
    Candle,
    Notification,
    Order,
    Position,
    Signal,
    TradingResult,
)
from botragram.services.position_exit_service import PositionExitService

_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _make_candle(
    *,
    index: int,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
) -> Candle:
    open_time = _NOW + timedelta(minutes=15 * index)
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M15,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=Decimal("100.0"),
    )


def _make_position(
    *,
    symbol: str = "BTCUSDT",
    side: PositionSide = PositionSide.SHORT,
    entry_price: Decimal = Decimal("50000"),
    current_price: Decimal = Decimal("50500"),
    quantity: Decimal = Decimal("0.1"),
    unrealized_pnl: Decimal = Decimal("-50"),
) -> Position:
    return Position(
        symbol=symbol,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        current_price=current_price,
        unrealized_pnl=unrealized_pnl,
        leverage=5,
        opened_at=_NOW,
        updated_at=_NOW,
    )


# =============================================================================
# Engine Tests
# =============================================================================
def test_position_exit_engine_disabled() -> None:
    engine = PositionExitEngine(enabled=False)
    pos = _make_position()
    dec = engine.evaluate(position=pos, candles=())
    assert dec.action is PositionExitAction.HOLD
    assert "disabled" in dec.reason


def test_position_exit_engine_zero_quantity() -> None:
    engine = PositionExitEngine(enabled=True)
    pos = _make_position(quantity=Decimal("0"))
    dec = engine.evaluate(position=pos, candles=())
    assert dec.action is PositionExitAction.HOLD
    assert "zero" in dec.reason


def test_position_exit_engine_in_profit() -> None:
    engine = PositionExitEngine(enabled=True)
    # Short position with current_price < entry_price is in profit
    pos_short_profit = _make_position(
        side=PositionSide.SHORT,
        entry_price=Decimal("50000"),
        current_price=Decimal("49500"),
        unrealized_pnl=Decimal("50"),
    )
    dec = engine.evaluate(position=pos_short_profit, candles=())
    assert dec.action is PositionExitAction.HOLD
    assert "in floating profit" in dec.reason

    # Long position with current_price > entry_price is in profit
    pos_long_profit = _make_position(
        side=PositionSide.LONG,
        entry_price=Decimal("50000"),
        current_price=Decimal("50500"),
        unrealized_pnl=Decimal("50"),
    )
    dec = engine.evaluate(position=pos_long_profit, candles=())
    assert dec.action is PositionExitAction.HOLD
    assert "in floating profit" in dec.reason


def test_position_exit_engine_opposite_signal_short() -> None:
    engine = PositionExitEngine(enabled=True, min_confidence=0.75)
    # Short position in floating loss (price went up to 50500)
    pos = _make_position(
        side=PositionSide.SHORT,
        entry_price=Decimal("50000"),
        current_price=Decimal("50500"),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("50500"),
        confidence=Decimal("0.85"),
        strategy_name="pinbar_engulfing",
        generated_at=_NOW,
        reason="Bullish crossover confirmed",
    )
    dec = engine.evaluate(position=pos, candles=(), strategy_signal=signal)
    assert dec.action is PositionExitAction.EARLY_CUT_LOSS
    assert dec.should_exit is True
    assert "Opposite strategy signal generated" in dec.reason
    assert dec.confidence == pytest.approx(0.85)


def test_position_exit_engine_opposite_signal_long() -> None:
    engine = PositionExitEngine(enabled=True, min_confidence=0.75)
    # Long position in floating loss (price went down to 49500)
    pos = _make_position(
        side=PositionSide.LONG,
        entry_price=Decimal("50000"),
        current_price=Decimal("49500"),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("49500"),
        confidence=Decimal("0.80"),
        strategy_name="pinbar_engulfing",
        generated_at=_NOW,
        reason="Bearish trend reversal",
    )
    dec = engine.evaluate(position=pos, candles=(), strategy_signal=signal)
    assert dec.action is PositionExitAction.EARLY_CUT_LOSS
    assert dec.should_exit is True
    assert "Opposite strategy signal generated" in dec.reason


def test_position_exit_engine_opposite_signal_low_confidence() -> None:
    engine = PositionExitEngine(enabled=True, min_confidence=0.75)
    pos = _make_position(side=PositionSide.SHORT)
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("50500"),
        confidence=Decimal("0.60"),  # Below 0.75
        strategy_name="pinbar_engulfing",
        generated_at=_NOW,
        reason="Weak signal",
    )
    dec = engine.evaluate(position=pos, candles=(), strategy_signal=signal)
    assert dec.action is PositionExitAction.HOLD


def test_position_exit_engine_bullish_engulfing_against_short() -> None:
    engine = PositionExitEngine(
        enabled=True,
        check_candlestick_reversal=True,
        check_opposite_signal=False,
    )
    pos = _make_position(
        side=PositionSide.SHORT,
        entry_price=Decimal("50000"),
        current_price=Decimal("50600"),
    )
    # Candle 0: Red candle (50200 -> 50000)
    c0 = _make_candle(
        index=0,
        open_price=Decimal("50200"),
        high_price=Decimal("50250"),
        low_price=Decimal("49950"),
        close_price=Decimal("50000"),
    )
    # Candle 1: Big green candle engulfing c0 (49980 -> 50600)
    c1 = _make_candle(
        index=1,
        open_price=Decimal("49980"),
        high_price=Decimal("50650"),
        low_price=Decimal("49950"),
        close_price=Decimal("50600"),
    )
    dec = engine.evaluate(position=pos, candles=(c0, c1))
    assert dec.action is PositionExitAction.EARLY_CUT_LOSS
    assert "Bullish engulfing" in dec.reason


def test_position_exit_engine_bearish_engulfing_against_long() -> None:
    engine = PositionExitEngine(
        enabled=True,
        check_candlestick_reversal=True,
        check_opposite_signal=False,
    )
    pos = _make_position(
        side=PositionSide.LONG,
        entry_price=Decimal("50000"),
        current_price=Decimal("49400"),
    )
    # Candle 0: Green candle (49800 -> 50000)
    c0 = _make_candle(
        index=0,
        open_price=Decimal("49800"),
        high_price=Decimal("50050"),
        low_price=Decimal("49750"),
        close_price=Decimal("50000"),
    )
    # Candle 1: Big red candle engulfing c0 (50020 -> 49400)
    c1 = _make_candle(
        index=1,
        open_price=Decimal("50020"),
        high_price=Decimal("50050"),
        low_price=Decimal("49350"),
        close_price=Decimal("49400"),
    )
    dec = engine.evaluate(position=pos, candles=(c0, c1))
    assert dec.action is PositionExitAction.EARLY_CUT_LOSS
    assert "Bearish engulfing" in dec.reason


def test_position_exit_engine_bullish_pinbar_against_short() -> None:
    engine = PositionExitEngine(
        enabled=True,
        check_candlestick_reversal=True,
        check_opposite_signal=False,
    )
    pos = _make_position(
        side=PositionSide.SHORT,
        entry_price=Decimal("50000"),
        current_price=Decimal("50200"),
    )
    c0 = _make_candle(
        index=0,
        open_price=Decimal("50200"),
        high_price=Decimal("50300"),
        low_price=Decimal("50000"),
        close_price=Decimal("50100"),
    )
    # Bullish hammer pinbar: long lower wick >= 60% of range, close near top
    c1 = _make_candle(
        index=1,
        open_price=Decimal("50100"),
        high_price=Decimal("50200"),
        low_price=Decimal("49400"),  # Range 800, lower wick 50100-49400 = 700 (87.5%)
        close_price=Decimal("50180"),
    )
    dec = engine.evaluate(position=pos, candles=(c0, c1))
    assert dec.action is PositionExitAction.EARLY_CUT_LOSS
    assert "Bullish pinbar" in dec.reason


# =============================================================================
# Service Mocking & Integration Tests
# =============================================================================
class _MockMarketService:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
    ) -> list[Candle]:
        del symbol, interval, limit
        return self.candles


class _MockStrategyService:
    def __init__(self, signal: Signal) -> None:
        self.signal = signal

    async def generate_and_save(self, *, candles: Sequence[Candle]) -> Signal:
        del candles
        return self.signal


class _MockLiveExchange:
    def __init__(self) -> None:
        self.cancelled_symbols: list[str | None] = []
        self.closed_positions: list[Position] = []

    async def cancel_all_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> list[Order]:
        self.cancelled_symbols.append(symbol)
        return []

    async def close_position_exact(
        self,
        *,
        position: Position,
        client_order_id: str,
    ) -> Order:
        self.closed_positions.append(position)
        return Order(
            order_id="12345",
            client_order_id=client_order_id,
            symbol=position.symbol,
            side=OrderSide.BUY
            if position.side is PositionSide.SHORT
            else OrderSide.SELL,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=position.quantity,
            price=position.current_price,
            executed_quantity=position.quantity,
            created_at=_NOW,
            updated_at=_NOW,
        )


class _MockPaperTradingService:
    def __init__(self) -> None:
        self.closed_symbols: list[str] = []

    async def close_position_for_early_exit(
        self,
        *,
        symbol: str,
        current_price: Decimal,
        closed_at: datetime,
        reason: str = "Early Cut Loss",
    ) -> TradingResult | None:
        del current_price, closed_at, reason
        self.closed_symbols.append(symbol)
        return None


class _MockLifecycleCoordinator:
    @asynccontextmanager
    async def hold(self, *, symbol: str) -> AsyncGenerator[None, None]:
        del symbol
        yield


class _MockNotificationPublisher:
    def __init__(self) -> None:
        self.notifications: list[Notification] = []

    async def publish(self, *, notification: Notification) -> None:
        self.notifications.append(notification)


@pytest.mark.asyncio
async def test_position_exit_service_disabled() -> None:
    engine = PositionExitEngine(enabled=False)
    service = PositionExitService(
        engine=engine,
        market_service=_MockMarketService([]),
    )
    decisions = await service.evaluate_open_positions(
        positions=[_make_position()],
        interval=Interval.M15,
    )
    assert decisions == ()


@pytest.mark.asyncio
async def test_position_exit_service_live_execution() -> None:
    engine = PositionExitEngine(enabled=True, min_confidence=0.75)
    exchange = _MockLiveExchange()
    notifier = _MockNotificationPublisher()
    pos = _make_position(side=PositionSide.SHORT)

    opposite_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("50500"),
        confidence=Decimal("0.85"),
        strategy_name="test",
        generated_at=_NOW,
        reason="Opposite entry detected",
    )

    service = PositionExitService(
        engine=engine,
        market_service=_MockMarketService([]),
        strategy_service=_MockStrategyService(opposite_signal),
        live_exchange=exchange,
        lifecycle_coordinator=_MockLifecycleCoordinator(),
        notification_publisher=notifier,
        trade_mode=TradeMode.LIVE,
    )

    decisions = await service.evaluate_open_positions(
        positions=[pos],
        interval=Interval.M15,
    )

    assert len(decisions) == 1
    assert decisions[0].action is PositionExitAction.EARLY_CUT_LOSS
    assert "BTCUSDT" in exchange.cancelled_symbols
    assert len(exchange.closed_positions) == 1
    assert exchange.closed_positions[0].symbol == "BTCUSDT"
    assert len(notifier.notifications) == 1
    assert "Early Cut Loss: BTCUSDT" in notifier.notifications[0].title


@pytest.mark.asyncio
async def test_position_exit_service_paper_execution() -> None:
    engine = PositionExitEngine(enabled=True, min_confidence=0.75)
    paper_service = _MockPaperTradingService()
    notifier = _MockNotificationPublisher()
    pos = _make_position(side=PositionSide.SHORT)

    opposite_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("50500"),
        confidence=Decimal("0.85"),
        strategy_name="test",
        generated_at=_NOW,
        reason="Opposite entry detected",
    )

    service = PositionExitService(
        engine=engine,
        market_service=_MockMarketService([]),
        strategy_service=_MockStrategyService(opposite_signal),
        paper_trading_service=paper_service,
        notification_publisher=notifier,
        trade_mode=TradeMode.PAPER,
    )

    decisions = await service.evaluate_open_positions(
        positions=[pos],
        interval=Interval.M15,
    )

    assert len(decisions) == 1
    assert decisions[0].action is PositionExitAction.EARLY_CUT_LOSS
    assert "BTCUSDT" in paper_service.closed_symbols
    assert len(notifier.notifications) == 1


def test_position_exit_engine_exhaustion_early_take_profit() -> None:
    """Trigger EARLY_TAKE_PROFIT when position exhibits exhaustion."""
    engine = PositionExitEngine(
        enabled=True, min_confidence=0.70, check_exhaustion=True
    )
    # Long position in floating profit
    pos = _make_position(
        side=PositionSide.LONG,
        entry_price=Decimal("110"),
        current_price=Decimal("150"),
        unrealized_pnl=Decimal("40"),
    )

    # 35 candles: rising sharply to trigger RSI > 70, then blow-off upper wick rejection
    candles: list[Candle] = []
    base = Decimal("100.0")
    for i in range(34):
        p = base + Decimal(str(i * 1.5))
        candles.append(
            _make_candle(
                index=i,
                open_price=p,
                high_price=p + Decimal("1.0"),
                low_price=p - Decimal("0.5"),
                close_price=p + Decimal("0.8"),
            )
        )

    # Candle 34: massive upper spike through Upper BB with rejection close
    p34 = candles[-1].close_price
    candles.append(
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M15,
            open_time=_NOW + timedelta(minutes=15 * 34),
            close_time=_NOW + timedelta(minutes=15 * 35),
            open_price=p34,
            high_price=p34 + Decimal("25.0"),  # Pierce way beyond Upper BB
            low_price=p34 - Decimal("2.0"),
            close_price=p34 - Decimal("1.0"),  # Close back inside band / rejection
            volume=Decimal("500.0"),  # 5x regular volume
        )
    )

    dec = engine.evaluate(position=pos, candles=candles)
    assert dec.action is PositionExitAction.EARLY_TAKE_PROFIT
    assert dec.should_exit is True
    assert "Early Take Profit: Multi-indicator exhaustion confluence" in dec.reason
    assert dec.confidence >= 0.70


@pytest.mark.asyncio
async def test_position_exit_service_early_take_profit_execution() -> None:
    """Execute paper close and send INFO notification on EARLY_TAKE_PROFIT decision."""
    engine = PositionExitEngine(
        enabled=True, min_confidence=0.70, check_exhaustion=True
    )
    paper_service = _MockPaperTradingService()
    notifier = _MockNotificationPublisher()
    pos = _make_position(
        side=PositionSide.LONG,
        entry_price=Decimal("110"),
        current_price=Decimal("150"),
        unrealized_pnl=Decimal("40"),
    )

    candles: list[Candle] = []
    base = Decimal("100.0")
    for i in range(34):
        p = base + Decimal(str(i * 1.5))
        candles.append(
            _make_candle(
                index=i,
                open_price=p,
                high_price=p + Decimal("1.0"),
                low_price=p - Decimal("0.5"),
                close_price=p + Decimal("0.8"),
            )
        )
    p34 = candles[-1].close_price
    candles.append(
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M15,
            open_time=_NOW + timedelta(minutes=15 * 34),
            close_time=_NOW + timedelta(minutes=15 * 35),
            open_price=p34,
            high_price=p34 + Decimal("25.0"),
            low_price=p34 - Decimal("2.0"),
            close_price=p34 - Decimal("1.0"),
            volume=Decimal("500.0"),
        )
    )

    service = PositionExitService(
        engine=engine,
        market_service=_MockMarketService(candles),
        paper_trading_service=paper_service,
        notification_publisher=notifier,
        trade_mode=TradeMode.PAPER,
    )

    decisions = await service.evaluate_open_positions(
        positions=[pos],
        interval=Interval.M15,
    )

    assert len(decisions) == 1
    assert decisions[0].action is PositionExitAction.EARLY_TAKE_PROFIT
    assert "BTCUSDT" in paper_service.closed_symbols
    assert len(notifier.notifications) == 1
    assert "Early Take Profit: BTCUSDT" in notifier.notifications[0].title
    assert "EARLY TAKE PROFIT EXECUTED" in notifier.notifications[0].message
