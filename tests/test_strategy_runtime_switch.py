"""Guarded in-process strategy session switching regressions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app import (
    MarketTypeSwitchService,
    RuntimeRestartCoordinator,
    TradingRuntimeControl,
    prepare_restarted_runtime_session,
)
from botragram.config import Settings
from botragram.enums import PositionSide, StrategyType, TradeMode
from botragram.exceptions import ExecutionPolicySwitchBlockedError
from botragram.models import Position

_NOW = datetime(2026, 8, 30, tzinfo=UTC)


@dataclass(slots=True, kw_only=True)
class _StoredPositions:
    positions: tuple[Position, ...] = ()

    async def get_open_positions(self) -> Sequence[Position]:
        return self.positions


@dataclass(slots=True, kw_only=True)
class _LivePositions:
    positions: tuple[Position, ...] = ()

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        del synchronize
        return self.positions


@dataclass(slots=True)
class _HomeMenuPublisher:
    refreshed: bool = False

    async def publish_home_menu_refresh(self) -> None:
        self.refreshed = True


def _position() -> Position:
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


@pytest.mark.asyncio
async def test_strategy_switch_stages_exact_soft_restart_target() -> None:
    """Rebuild the session so immutable autonomous executors use the new strategy."""
    coordinator = RuntimeRestartCoordinator()
    service = MarketTypeSwitchService(
        trade_mode=TradeMode.PAPER,
        runtime_control=TradingRuntimeControl(),
        position_repository=_StoredPositions(),
        position_service=_LivePositions(),
        restart_coordinator=coordinator,
        settings=Settings(),
    )

    assert service.current_strategy_type is StrategyType.EMA_CROSS
    assert await service.prepare_strategy(strategy_type=StrategyType.EMA_SCALPING)
    assert coordinator.consume() is None

    service.commit_strategy(strategy_type=StrategyType.EMA_SCALPING)

    assert await coordinator.wait() is StrategyType.EMA_SCALPING
    assert coordinator.consume() is StrategyType.EMA_SCALPING


@pytest.mark.asyncio
async def test_strategy_switch_rejects_open_positions() -> None:
    """Keep strategy provenance stable until the portfolio is flat."""
    coordinator = RuntimeRestartCoordinator()
    service = MarketTypeSwitchService(
        trade_mode=TradeMode.PAPER,
        runtime_control=TradingRuntimeControl(),
        position_repository=_StoredPositions(positions=(_position(),)),
        position_service=_LivePositions(),
        restart_coordinator=coordinator,
        settings=Settings(),
    )

    with pytest.raises(
        ExecutionPolicySwitchBlockedError,
        match="Close every active position before switching strategy",
    ):
        await service.prepare_strategy(strategy_type=StrategyType.EMA_SCALPING)

    assert coordinator.consume() is None


@pytest.mark.asyncio
async def test_strategy_restart_session_remains_paused() -> None:
    """Require explicit operator resume after a strategy session rebuild."""
    runtime_control = TradingRuntimeControl()
    runtime_control.resume_global_cycle()
    publisher = _HomeMenuPublisher()

    await prepare_restarted_runtime_session(
        restart_target=StrategyType.EMA_SCALPING,
        runtime_control=runtime_control,
        home_menu_publisher=publisher,
    )

    assert runtime_control.is_paused
    assert publisher.refreshed
