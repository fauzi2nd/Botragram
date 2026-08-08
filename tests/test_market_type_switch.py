"""Guarded Binance Spot and Futures runtime-switch tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app import (
    MarketTypeSwitchService,
    RuntimeRestartCoordinator,
    TradingRuntimeControl,
    run_until_restart,
)
from botragram.enums import MarketType, PositionSide, TradeMode
from botragram.models import Position

_NOW = datetime(2026, 8, 7, tzinfo=UTC)


@dataclass(slots=True, kw_only=True)
class FakeStoredPositions:
    """Return deterministic paper positions."""

    positions: tuple[Position, ...] = ()

    async def get_open_positions(self) -> Sequence[Position]:
        """Return configured paper positions."""
        return self.positions


@dataclass(slots=True, kw_only=True)
class FakeLivePositions:
    """Record whether live positions are synchronized before switching."""

    positions: tuple[Position, ...] = ()
    synchronized: bool = False

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        """Return configured live positions and record synchronization intent."""
        self.synchronized = synchronize
        return self.positions


@dataclass(slots=True)
class FakeStoppableRunner:
    """Remain active until the soft-restart orchestrator stops the runner."""

    stopped: bool = False
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event)

    async def run(self) -> None:
        """Wait for the graceful stop signal."""
        await self._stop_event.wait()

    def stop(self) -> None:
        """Record and release a graceful stop request."""
        self.stopped = True
        self._stop_event.set()


def _position() -> Position:
    """Return one active position that must block connector replacement."""
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("0.01"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )


def test_market_type_switch_is_staged_and_committed_separately() -> None:
    """Keep the old connector alive until Telegram acknowledgement succeeds."""
    asyncio.run(_run_staged_switch_test())


def test_current_market_type_is_confirmed_without_a_restart() -> None:
    """Treat the loaded product as selected only after its Telegram callback."""
    asyncio.run(_run_current_market_type_confirmation_test())


async def _run_current_market_type_confirmation_test() -> None:
    """Confirm Spot and leave the restart coordinator inactive."""
    coordinator = RuntimeRestartCoordinator()
    runtime_control = TradingRuntimeControl(market_type=MarketType.SPOT)
    service = MarketTypeSwitchService(
        trade_mode=TradeMode.PAPER,
        runtime_control=runtime_control,
        position_repository=FakeStoredPositions(),
        position_service=FakeLivePositions(),
        restart_coordinator=coordinator,
    )

    assert "market type" in runtime_control.get_missing_configuration_requirements()
    assert not await service.prepare(market_type=MarketType.SPOT)
    assert "market type" not in runtime_control.get_missing_configuration_requirements()
    assert coordinator.consume() is None


def test_committed_switch_stops_the_active_runner() -> None:
    """Wake the application session and terminate trading gracefully."""
    asyncio.run(_run_committed_restart_test())


async def _run_committed_restart_test() -> None:
    """Commit Futures while the runner waits for its stop signal."""
    coordinator = RuntimeRestartCoordinator()
    runner = FakeStoppableRunner()
    session_task = asyncio.create_task(
        run_until_restart(
            runner=runner,
            restart_coordinator=coordinator,
        )
    )
    await asyncio.sleep(0)

    coordinator.stage(market_type=MarketType.FUTURES)
    coordinator.commit(market_type=MarketType.FUTURES)
    await session_task

    assert runner.stopped


async def _run_staged_switch_test() -> None:
    """Stage Futures, verify no restart, then commit the soft restart."""
    coordinator = RuntimeRestartCoordinator()
    service = MarketTypeSwitchService(
        trade_mode=TradeMode.PAPER,
        runtime_control=TradingRuntimeControl(market_type=MarketType.SPOT),
        position_repository=FakeStoredPositions(),
        position_service=FakeLivePositions(),
        restart_coordinator=coordinator,
    )

    assert await service.prepare(market_type=MarketType.FUTURES)
    assert coordinator.consume() is None

    service.commit(market_type=MarketType.FUTURES)

    assert await coordinator.wait() is MarketType.FUTURES
    assert coordinator.consume() is MarketType.FUTURES
    assert coordinator.consume() is None


def test_market_type_switch_requires_a_safe_runtime_state() -> None:
    """Reject connector replacement while trading or streaming is active."""
    asyncio.run(_run_unsafe_runtime_test())


async def _run_unsafe_runtime_test() -> None:
    """Attempt product switching while the stream owns runtime state."""
    runtime_control = TradingRuntimeControl(market_type=MarketType.SPOT)
    runtime_control.set_stream_enabled(True)
    service = MarketTypeSwitchService(
        trade_mode=TradeMode.PAPER,
        runtime_control=runtime_control,
        position_repository=FakeStoredPositions(),
        position_service=FakeLivePositions(),
        restart_coordinator=RuntimeRestartCoordinator(),
    )

    with pytest.raises(RuntimeError, match="Stop the market stream"):
        await service.prepare(market_type=MarketType.FUTURES)


def test_market_type_switch_fails_closed_for_live_positions() -> None:
    """Synchronize live positions and block a product switch when one exists."""
    asyncio.run(_run_live_position_guard_test())


async def _run_live_position_guard_test() -> None:
    """Verify the active connector is queried before a live restart."""
    live_positions = FakeLivePositions(positions=(_position(),))
    service = MarketTypeSwitchService(
        trade_mode=TradeMode.LIVE,
        runtime_control=TradingRuntimeControl(market_type=MarketType.FUTURES),
        position_repository=FakeStoredPositions(),
        position_service=live_positions,
        restart_coordinator=RuntimeRestartCoordinator(),
    )

    with pytest.raises(RuntimeError, match="active position"):
        await service.prepare(market_type=MarketType.SPOT)

    assert live_positions.synchronized
