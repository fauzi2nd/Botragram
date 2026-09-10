"""
Botragram

Description:
    Unit tests for dynamic live stream PnL and price synchronization in
    TelegramQueryService.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine.pnl_engine import PnLEngine
from botragram.enums import (
    Interval,
    LiveFuturesUserDataStatus,
    LiveMarketStreamLifecycleStatus,
    LiveRuntimeHealthStatus,
    PositionSide,
)
from botragram.models import (
    FuturesUserDataPositionUpdate,
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveRuntimeHealthSnapshot,
    Position,
    Ticker,
)
from botragram.services.live_futures_user_data_cache import (
    LiveFuturesUserDataSnapshot,
)
from botragram.services.live_market_stream_service import LiveMarketStreamService
from botragram.storage.memory import (
    MemoryOrderRepository,
    MemoryPositionRepository,
    MemoryTradeRepository,
)
from botragram.telegram.query_service import TelegramQueryService

# =============================================================================
# Constants
# =============================================================================
_NOW: Final[datetime] = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


class _FakeMarketService:
    async def get_ticker(self, *, symbol: str) -> Ticker:
        return Ticker(
            symbol=symbol,
            last_price=Decimal("100"),
            bid_price=Decimal("99"),
            ask_price=Decimal("101"),
            timestamp=_NOW,
        )

    async def get_trading_symbols(self, *, quote_asset: str) -> tuple[str, ...]:
        del quote_asset
        return ("PTBUSDT", "BTCUSDT")

    @property
    def is_stream_connected(self) -> bool:
        return True

    async def stream_ticker(self, *, symbol: str) -> AsyncIterator[Ticker]:
        del symbol
        if False:
            yield Ticker(
                symbol="BTCUSDT",
                last_price=Decimal("100"),
                bid_price=Decimal("99"),
                ask_price=Decimal("101"),
                timestamp=_NOW,
            )

    async def unsubscribe(self, *, symbol: str) -> None:
        del symbol


class _FakePaperBalance:
    async def get_available_balance(self) -> Decimal:
        return Decimal("1000")


class _FakeLiveHealth:
    def __init__(self, stream_states: tuple[LiveMarketStreamState, ...]) -> None:
        self.stream_states = stream_states

    def get_snapshot(self) -> LiveRuntimeHealthSnapshot:
        return LiveRuntimeHealthSnapshot(
            status=LiveRuntimeHealthStatus.ACTIVE,
            reason=None,
            contexts=(),
            affected_contexts=(),
            authorization_present=True,
            authorization_exact=True,
            runner_paused=False,
            cycle_in_progress=False,
            stream_states=self.stream_states,
            monitor_states=(),
        )


class _FakeUserData:
    def __init__(self, snapshot: LiveFuturesUserDataSnapshot) -> None:
        self.snapshot = snapshot

    async def get_snapshot(self) -> LiveFuturesUserDataSnapshot:
        return self.snapshot


@pytest.mark.asyncio
async def test_telegram_query_service_refreshes_pnl_from_live_stream() -> None:
    positions = MemoryPositionRepository()
    orders = MemoryOrderRepository()
    trades = MemoryTradeRepository()
    pnl_engine = PnLEngine()
    market_service = _FakeMarketService()
    stream_service = LiveMarketStreamService(market_service=market_service)

    # Initial position: Short entered at 0.0006518 with static stale PnL -0.02
    await positions.save(
        position=Position(
            symbol="PTBUSDT",
            side=PositionSide.SHORT,
            quantity=Decimal("15330"),
            entry_price=Decimal("0.0006518"),
            current_price=Decimal("0.0006518"),
            unrealized_pnl=Decimal("-0.02"),
            leverage=5,
            opened_at=_NOW,
            updated_at=_NOW,
        )
    )

    # Live market stream for PTBUSDT price dropped to 0.000645 (profit for short)
    stream_state = LiveMarketStreamState(
        identity=LiveMarketStreamIdentity(
            symbol="PTBUSDT",
            interval=Interval.M15,
        ),
        lifecycle_status=LiveMarketStreamLifecycleStatus.RUNNING,
        first_tick_received=True,
        event_count=50,
        last_price=Decimal("0.000645"),
        last_event_monotonic=100.0,
    )
    health_service = _FakeLiveHealth(stream_states=(stream_state,))

    service = TelegramQueryService(
        symbol="PTBUSDT",
        market_service=market_service,
        paper_trading_service=_FakePaperBalance(),
        position_repository=positions,
        trade_repository=trades,
        order_repository=orders,
        market_stream_service=stream_service,
        live_runtime_health_service=health_service,
        pnl_engine=pnl_engine,
    )

    refreshed_positions = await service.get_positions()
    assert len(refreshed_positions) == 1
    pos = refreshed_positions[0]
    assert pos.symbol == "PTBUSDT"
    assert pos.current_price == Decimal("0.000645")
    # (0.0006518 - 0.000645) * 15330 = +0.104244
    assert pos.unrealized_pnl == Decimal("0.104244")


@pytest.mark.asyncio
async def test_telegram_query_service_overlays_user_data_updates() -> None:
    positions = MemoryPositionRepository()
    orders = MemoryOrderRepository()
    trades = MemoryTradeRepository()
    market_service = _FakeMarketService()
    stream_service = LiveMarketStreamService(market_service=market_service)

    await positions.save(
        position=Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("0.1"),
            entry_price=Decimal("60000"),
            current_price=Decimal("60000"),
            unrealized_pnl=Decimal("0"),
            leverage=10,
            opened_at=_NOW,
            updated_at=_NOW,
        )
    )

    user_data = _FakeUserData(
        LiveFuturesUserDataSnapshot(
            status=LiveFuturesUserDataStatus.READY,
            last_event_at=_NOW,
            last_snapshot_at=_NOW,
            balances=(),
            positions=(),
            position_updates=(
                FuturesUserDataPositionUpdate(
                    symbol="BTCUSDT",
                    quantity=Decimal("0.2"),
                    entry_price=Decimal("60500"),
                    unrealized_pnl=Decimal("25.50"),
                ),
            ),
            recent_orders=(),
        )
    )

    service = TelegramQueryService(
        symbol="BTCUSDT",
        market_service=market_service,
        paper_trading_service=_FakePaperBalance(),
        position_repository=positions,
        trade_repository=trades,
        order_repository=orders,
        market_stream_service=stream_service,
        live_futures_user_data_service=user_data,
    )

    refreshed = await service.get_positions()
    assert len(refreshed) == 1
    pos = refreshed[0]
    assert pos.quantity == Decimal("0.2")
    assert pos.entry_price == Decimal("60500")
    assert pos.unrealized_pnl == Decimal("25.50")
