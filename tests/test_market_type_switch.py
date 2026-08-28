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
from botragram.config import Settings
from botragram.config.app_settings import AppSettings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.config.telegram_settings import TelegramSettings
from botragram.enums import (
    ExchangeType,
    ExecutionPolicy,
    MarketType,
    PositionSide,
    TradeMode,
)
from botragram.exceptions import ExecutionPolicySwitchBlockedError
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


@dataclass(slots=True, kw_only=True)
class FakeIncompleteSubmissions:
    """Return deterministic incomplete LIVE submission ownership."""

    incomplete: tuple[object, ...] = ()

    async def get_incomplete(self) -> Sequence[object]:
        """Return configured incomplete attempts."""
        return self.incomplete


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


def test_execution_policy_switch_uses_shared_soft_restart() -> None:
    """Switch PAPER workflow without terminating the Botragram process."""
    asyncio.run(_run_execution_policy_switch_test())


async def _run_execution_policy_switch_test() -> None:
    """Stage and commit autonomous PAPER through the shared coordinator."""
    coordinator = RuntimeRestartCoordinator()
    service = MarketTypeSwitchService(
        trade_mode=TradeMode.PAPER,
        runtime_control=TradingRuntimeControl(),
        position_repository=FakeStoredPositions(),
        position_service=FakeLivePositions(),
        restart_coordinator=coordinator,
        settings=Settings(telegram=TelegramSettings(enabled=False)),
        submission_attempt_repository=FakeIncompleteSubmissions(),
    )

    assert ExecutionPolicy.AUTONOMOUS_PAPER in service.available_execution_policies()
    assert await service.prepare_execution_policy(
        execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER
    )
    service.commit_execution_policy(execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER)

    assert await coordinator.wait() is ExecutionPolicy.AUTONOMOUS_PAPER
    assert coordinator.consume() is ExecutionPolicy.AUTONOMOUS_PAPER


def test_live_execution_policy_switch_requires_clean_submission_state() -> None:
    """Keep incomplete LIVE submission ownership authoritative during switching."""
    asyncio.run(_run_live_execution_policy_recovery_guard_test())


async def _run_live_execution_policy_recovery_guard_test() -> None:
    """Reject autonomous activation while an incomplete LIVE attempt exists."""
    settings = Settings(
        app=AppSettings(
            trade_mode=TradeMode.LIVE,
            execution_policy=ExecutionPolicy.SINGLE_SYMBOL,
            autonomous_live_entry_enabled=True,
        ),
        exchange=ExchangeSettings(
            exchange=ExchangeType.BINANCE,
            market_type=MarketType.FUTURES,
            api_key="key",
            api_secret="secret",
            testnet=True,
        ),
        telegram=TelegramSettings(enabled=False),
    )
    service = MarketTypeSwitchService(
        trade_mode=TradeMode.LIVE,
        runtime_control=TradingRuntimeControl(market_type=MarketType.FUTURES),
        position_repository=FakeStoredPositions(),
        position_service=FakeLivePositions(),
        restart_coordinator=RuntimeRestartCoordinator(),
        settings=settings,
        submission_attempt_repository=FakeIncompleteSubmissions(incomplete=(object(),)),
    )

    assert ExecutionPolicy.AUTONOMOUS_LIVE in service.available_execution_policies()
    with pytest.raises(
        ExecutionPolicySwitchBlockedError,
        match="Incomplete LIVE submission",
    ):
        await service.prepare_execution_policy(
            execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE
        )


def test_restart_coordinator_exposes_committed_pre_runner_restart() -> None:
    coordinator = RuntimeRestartCoordinator()
    coordinator.stage(execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER)
    assert not coordinator.has_committed_restart
    coordinator.commit(execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER)
    assert coordinator.has_committed_restart
    assert coordinator.consume() is ExecutionPolicy.AUTONOMOUS_PAPER
    assert not coordinator.has_committed_restart


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


@pytest.mark.asyncio
async def test_execution_policy_position_block_is_typed_and_stages_no_restart() -> None:
    """Expose guarded flatten eligibility without staging a rejected transition."""
    coordinator = RuntimeRestartCoordinator()
    service = MarketTypeSwitchService(
        trade_mode=TradeMode.PAPER,
        runtime_control=TradingRuntimeControl(),
        position_repository=FakeStoredPositions(positions=(_position(),)),
        position_service=FakeLivePositions(),
        restart_coordinator=coordinator,
        settings=Settings(telegram=TelegramSettings(enabled=False)),
    )

    with pytest.raises(ExecutionPolicySwitchBlockedError) as captured:
        await service.prepare_execution_policy(
            execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER,
        )

    assert captured.value.active_position_count == 1
    assert "Close every active position" in str(captured.value)
    assert not coordinator.has_committed_restart
    assert coordinator.consume() is None
