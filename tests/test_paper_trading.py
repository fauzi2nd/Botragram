"""
Botragram

Description:
    Persistent paper execution and portfolio lifecycle tests.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from botragram.config.risk_settings import RiskSettings
from botragram.engine import PnLEngine, RiskEngine, TradingEngine
from botragram.enums import OrderSide, PositionSide, SignalType
from botragram.models import Notification, Position, Signal
from botragram.services import NotificationPublisher, PaperTradingService
from botragram.storage.memory import (
    MemoryOrderRepository,
    MemoryPositionRepository,
    MemoryTradeRepository,
)
from botragram.storage.sqlite import (
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLitePositionRepository,
)

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(slots=True, kw_only=True)
class PaperFixture:
    """Paper service and observable in-memory persistence."""

    service: PaperTradingService
    orders: MemoryOrderRepository
    trades: MemoryTradeRepository
    positions: MemoryPositionRepository


@dataclass(slots=True, kw_only=True)
class RecordingPublisher:
    """Capture notifications or simulate an unavailable delivery channel."""

    fail: bool = False
    notifications: list[Notification] = field(default_factory=list[Notification])

    async def publish(self, *, notification: Notification) -> None:
        """Capture a notification or raise a deterministic failure."""
        if self.fail:
            raise RuntimeError("telegram unavailable")

        self.notifications.append(notification)


def _create_fixture(
    *,
    initial_balance: Decimal = Decimal("10000"),
    max_open_positions: int = 1,
    notification_publisher: NotificationPublisher | None = None,
) -> PaperFixture:
    """Create an isolated paper portfolio."""
    orders = MemoryOrderRepository()
    trades = MemoryTradeRepository()
    positions = MemoryPositionRepository()
    service = PaperTradingService(
        order_repository=orders,
        trade_repository=trades,
        position_repository=positions,
        trading_engine=TradingEngine(
            risk_engine=RiskEngine(
                settings=RiskSettings(max_open_positions=max_open_positions),
            ),
        ),
        pnl_engine=PnLEngine(),
        notification_publisher=notification_publisher,
        initial_balance=initial_balance,
    )
    return PaperFixture(
        service=service,
        orders=orders,
        trades=trades,
        positions=positions,
    )


def _create_signal(
    *,
    signal_type: SignalType,
    price: Decimal,
    symbol: str = "BTCUSDT",
    generated_at: datetime = _NOW,
) -> Signal:
    """Create a deterministic paper signal."""
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        price=price,
        confidence=Decimal("0.8"),
        strategy_name="paper_test",
        generated_at=generated_at,
    )


def test_paper_service_opens_and_persists_a_long_position() -> None:
    """Simulate an entry with adverse slippage, fee, and reserved balance."""
    asyncio.run(_run_open_position_test())


async def _run_open_position_test() -> None:
    """Execute and inspect a simulated long entry."""
    fixture = _create_fixture()
    result = await fixture.service.execute(
        signal=_create_signal(signal_type=SignalType.BUY, price=Decimal("100")),
    )

    position = await fixture.positions.get_by_symbol(symbol="BTCUSDT")
    trades = await fixture.trades.get_latest(limit=10)
    balance = await fixture.service.get_available_balance()

    assert result.executed
    assert result.order is not None
    assert result.order.side is OrderSide.BUY
    assert result.order.price == Decimal("100.0500")
    assert position is not None
    assert position.side is PositionSide.LONG
    assert position.entry_price == Decimal("100.0500")
    assert position.stop_loss == Decimal("98.049000")
    assert position.take_profit == Decimal("104.052000")
    assert trades[0].fee == Decimal("1.0005000")
    assert balance == Decimal("8998.4995000")


def test_paper_service_marks_then_closes_at_take_profit() -> None:
    """Persist unrealized PnL, close the position, and realize net PnL."""
    asyncio.run(_run_position_lifecycle_test())


async def _run_position_lifecycle_test() -> None:
    """Exercise mark-to-market and take-profit lifecycle behavior."""
    publisher = RecordingPublisher()
    fixture = _create_fixture(notification_publisher=publisher)
    await fixture.service.execute(
        signal=_create_signal(signal_type=SignalType.BUY, price=Decimal("100")),
    )
    mark_time = _NOW + timedelta(minutes=1)
    mark_result = await fixture.service.execute(
        signal=_create_signal(
            signal_type=SignalType.HOLD,
            price=Decimal("101"),
            generated_at=mark_time,
        ),
    )
    marked_position = await fixture.positions.get_by_symbol(symbol="BTCUSDT")

    assert not mark_result.executed
    assert marked_position is not None
    assert marked_position.current_price == Decimal("101")
    assert marked_position.unrealized_pnl == Decimal("9.5000")

    close_time = _NOW + timedelta(minutes=2)
    close_signal = _create_signal(
        signal_type=SignalType.SELL,
        price=Decimal("105"),
        generated_at=close_time,
    )
    close_result = await fixture.service.execute(signal=close_signal)
    final_balance = await fixture.service.get_available_balance()
    realized_pnl = await fixture.service.get_realized_pnl()

    assert close_result.executed
    assert "take-profit" in close_result.reason
    assert await fixture.positions.get_by_symbol(symbol="BTCUSDT") is None
    assert await fixture.orders.count() == 2
    assert await fixture.trades.count() == 2
    assert final_balance == Decimal("10046.9250250")
    assert realized_pnl == Decimal("46.9250250")
    assert len(publisher.notifications) == 2
    assert "Paper Entry" in publisher.notifications[0].message
    assert "Paper Exit" in publisher.notifications[1].message
    assert "Realized PnL" in publisher.notifications[1].message

    duplicate_result = await fixture.service.execute(signal=close_signal)

    assert not duplicate_result.executed
    assert "already executed" in duplicate_result.reason
    assert await fixture.orders.count() == 2


def test_notification_failure_does_not_rollback_a_paper_fill() -> None:
    """Keep persisted execution authoritative when Telegram is unavailable."""
    asyncio.run(_run_notification_failure_test())


async def _run_notification_failure_test() -> None:
    """Execute an entry through a failing publisher."""
    fixture = _create_fixture(
        notification_publisher=RecordingPublisher(fail=True),
    )
    result = await fixture.service.execute(
        signal=_create_signal(signal_type=SignalType.BUY, price=Decimal("100")),
    )

    assert result.executed
    assert await fixture.orders.count() == 1
    assert await fixture.trades.count() == 1
    assert await fixture.positions.count() == 1


def test_paper_service_blocks_orders_exceeding_free_balance() -> None:
    """Reject a fill when slippage and fees exceed available paper funds."""
    asyncio.run(_run_insufficient_balance_test())


async def _run_insufficient_balance_test() -> None:
    """Attempt an entry with no room for execution costs."""
    fixture = _create_fixture(initial_balance=Decimal("100"))
    result = await fixture.service.execute(
        signal=_create_signal(signal_type=SignalType.BUY, price=Decimal("100")),
    )

    assert not result.executed
    assert "Insufficient paper balance" in result.reason
    assert await fixture.orders.count() == 0
    assert await fixture.positions.count() == 0


def test_paper_service_allows_entries_below_portfolio_capacity() -> None:
    """Allow distinct candidates while persisted capacity remains available."""
    asyncio.run(_run_below_capacity_test())


async def _run_below_capacity_test() -> None:
    """Open two distinct PAPER positions under a two-position limit."""
    fixture = _create_fixture(max_open_positions=2)
    first_result = await fixture.service.execute(
        signal=_create_signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100"),
        ),
    )
    second_result = await fixture.service.execute(
        signal=_create_signal(
            symbol="ETHUSDT",
            signal_type=SignalType.SELL,
            price=Decimal("100"),
            generated_at=_NOW + timedelta(minutes=1),
        ),
    )

    assert first_result.executed
    assert second_result.executed
    assert await fixture.positions.count() == 2


def test_paper_service_blocks_second_candidate_when_one_slot_is_available() -> None:
    """Make candidate two observe candidate one's persisted position."""
    asyncio.run(_run_one_slot_capacity_test())


async def _run_one_slot_capacity_test() -> None:
    """Open one position, then reject a different candidate at capacity."""
    fixture = _create_fixture(max_open_positions=1)
    first_result = await fixture.service.execute(
        signal=_create_signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100"),
        ),
    )
    second_result = await fixture.service.execute(
        signal=_create_signal(
            symbol="ETHUSDT",
            signal_type=SignalType.SELL,
            price=Decimal("100"),
            generated_at=_NOW + timedelta(minutes=1),
        ),
    )

    assert first_result.executed
    assert not second_result.executed
    assert second_result.reason == "Maximum open positions reached"
    assert await fixture.orders.count() == 1
    assert await fixture.positions.count() == 1


def test_paper_service_blocks_a_duplicate_symbol_entry() -> None:
    """Keep an existing symbol position authoritative over a new entry signal."""
    asyncio.run(_run_duplicate_symbol_test())


async def _run_duplicate_symbol_test() -> None:
    """Attempt a second BUY signal for an already-open PAPER position."""
    fixture = _create_fixture(max_open_positions=2)
    first_result = await fixture.service.execute(
        signal=_create_signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100"),
        ),
    )
    duplicate_result = await fixture.service.execute(
        signal=_create_signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("101"),
            generated_at=_NOW + timedelta(minutes=1),
        ),
    )

    assert first_result.executed
    assert not duplicate_result.executed
    assert duplicate_result.reason == "Paper position remains open"
    assert await fixture.orders.count() == 1
    assert await fixture.positions.count() == 1


def test_paper_service_serializes_concurrent_capacity_checks() -> None:
    """Ensure concurrent candidates cannot both consume one persisted slot."""
    asyncio.run(_run_concurrent_capacity_test())


async def _run_concurrent_capacity_test() -> None:
    """Submit two different candidates concurrently against one open slot."""
    fixture = _create_fixture(max_open_positions=1)
    first_signal = _create_signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
    )
    second_signal = _create_signal(
        symbol="ETHUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("100"),
        generated_at=_NOW + timedelta(minutes=1),
    )
    results = await asyncio.gather(
        fixture.service.execute(signal=first_signal),
        fixture.service.execute(signal=second_signal),
    )

    assert sum(result.executed for result in results) == 1
    assert await fixture.orders.count() == 1
    assert await fixture.positions.count() == 1


def test_sqlite_migration_persists_paper_exit_levels() -> None:
    """Verify protective prices survive a database round trip."""
    asyncio.run(_run_sqlite_position_metadata_test())


async def _run_sqlite_position_metadata_test() -> None:
    """Persist paper position metadata through the latest SQLite schema."""
    with TemporaryDirectory() as temporary_directory:
        database = SQLiteDatabase(
            database_path=Path(temporary_directory) / "paper.db",
        )
        await database.connect()

        try:
            version = await SQLiteMigrationManager(database=database).initialize()
            repository = SQLitePositionRepository(database=database)
            position = Position(
                symbol="BTCUSDT",
                side=PositionSide.LONG,
                quantity=Decimal("1"),
                entry_price=Decimal("100"),
                current_price=Decimal("100"),
                unrealized_pnl=Decimal("0"),
                leverage=1,
                opened_at=_NOW,
                updated_at=_NOW,
                stop_loss=Decimal("98"),
                take_profit=Decimal("104"),
            )
            await repository.save(position=position)
            stored_position = await repository.get_by_symbol(symbol="BTCUSDT")

            assert version == 10
            assert stored_position == position
        finally:
            await database.close()
