"""Private Futures User Data Stream lifecycle regressions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app.live_futures_user_data_service import LiveFuturesUserDataService
from botragram.enums import (
    FuturesAlgoOrderStatus,
    Interval,
    LiveFuturesUserDataStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.models import (
    Account,
    Balance,
    FuturesUserDataAccountUpdate,
    FuturesUserDataAlgoUpdate,
    FuturesUserDataEvent,
    FuturesUserDataOrderUpdate,
    FuturesUserDataPositionUpdate,
    FuturesUserDataStreamConnected,
    Order,
    Position,
)
from botragram.services.live_futures_user_data_cache import LiveFuturesUserDataCache

_NOW = datetime(2026, 8, 25, tzinfo=UTC)


def _position() -> Position:
    """Create one authoritative REST startup position."""
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("101"),
        unrealized_pnl=Decimal("1"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        interval=Interval.M1,
    )


def _order() -> Order:
    """Create one normalized private order update."""
    return Order(
        order_id="123",
        client_order_id="btg-123",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        quantity=Decimal("1"),
        executed_quantity=Decimal("1"),
        price=None,
        stop_price=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


@dataclass(slots=True)
class FakeSnapshotProvider:
    """Return one deterministic REST snapshot while counting resynchronization."""

    calls: int = 0

    async def get_account(self) -> Account:
        """Return one Futures account balance snapshot."""
        self.calls += 1
        return Account(
            balances=(Balance(asset="USDT", free=Decimal("100"), locked=Decimal("0")),)
        )

    async def get_positions(self, *, symbol: str | None = None) -> Sequence[Position]:
        """Return one Futures position snapshot."""
        assert symbol is None
        return (_position(),)


@dataclass(slots=True)
class FakeEventStream:
    """Yield configured private events then remain connected until shutdown."""

    events: tuple[FuturesUserDataEvent, ...]
    delivered: asyncio.Event = field(default_factory=asyncio.Event)
    released: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False

    async def stream_events(self) -> AsyncIterator[FuturesUserDataEvent]:
        """Yield private events without any REST polling."""
        for event in self.events:
            yield event
        self.delivered.set()
        await self.released.wait()

    async def close(self) -> None:
        """Release the active deterministic stream."""
        self.closed = True
        self.released.set()


@pytest.mark.asyncio
async def test_user_data_stream_cache_uses_startup_snapshot_then_events() -> None:
    """Update balance, position, and order cache without another REST read."""
    account_update = FuturesUserDataAccountUpdate(
        observed_at=_NOW,
        balances=(Balance(asset="USDT", free=Decimal("125"), locked=Decimal("0")),),
        positions=(
            FuturesUserDataPositionUpdate(
                symbol="BTCUSDT",
                quantity=Decimal("2"),
                entry_price=Decimal("100"),
                unrealized_pnl=Decimal("4"),
            ),
        ),
    )
    stream = FakeEventStream(
        events=(
            FuturesUserDataStreamConnected(observed_at=_NOW),
            account_update,
            FuturesUserDataOrderUpdate(observed_at=_NOW, order=_order()),
            FuturesUserDataAlgoUpdate(
                observed_at=_NOW,
                client_algo_id="bsl-123",
                algo_id="123",
                symbol="BTCUSDT",
                status=FuturesAlgoOrderStatus.TRIGGERING,
                order_type=OrderType.STOP_MARKET,
                trigger_price=Decimal("95"),
            ),
        )
    )
    snapshots = FakeSnapshotProvider()
    service = LiveFuturesUserDataService(
        snapshot_provider=snapshots,
        event_stream=stream,
    )

    await service.start()
    await stream.delivered.wait()

    assert snapshots.calls == 1
    assert await service.get_free_balance(asset="usdt") == Decimal("125")
    assert await service.get_equity(asset="USDT") == Decimal("129")
    snapshot = await service.cache.get_snapshot()
    assert snapshot.status is LiveFuturesUserDataStatus.READY
    assert snapshot.last_snapshot_at is not None
    assert snapshot.last_event_at == _NOW
    assert snapshot.positions[0].quantity == Decimal("2")
    assert snapshot.position_updates[0].quantity == Decimal("2")
    assert snapshot.recent_orders == (_order(),)
    assert snapshot.recent_algo_updates[0].client_algo_id == "bsl-123"

    await service.cache.apply(
        event=FuturesUserDataAccountUpdate(
            observed_at=_NOW,
            balances=(),
            positions=(
                FuturesUserDataPositionUpdate(
                    symbol="BTCUSDT",
                    quantity=Decimal("0"),
                    entry_price=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                ),
            ),
        )
    )
    closed_snapshot = await service.get_snapshot()
    assert closed_snapshot.positions == ()
    assert closed_snapshot.position_updates == ()

    await service.close()

    assert stream.closed


@pytest.mark.asyncio
async def test_user_data_cache_exposes_resync_and_stale_freshness() -> None:
    """Expose stale cached state instead of presenting it as current."""
    cache = LiveFuturesUserDataCache()

    await cache.mark_resyncing()
    assert (await cache.get_snapshot()).status is LiveFuturesUserDataStatus.RESYNCING

    await cache.mark_stale()
    assert (await cache.get_snapshot()).status is LiveFuturesUserDataStatus.STALE
