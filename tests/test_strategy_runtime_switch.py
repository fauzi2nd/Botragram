"""PIER-only strategy switching and runtime restart regressions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from botragram.app import (
    MarketTypeSwitchService,
    RuntimeRestartCoordinator,
    TradingRuntimeControl,
    prepare_restarted_runtime_session,
)
from botragram.config import Settings
from botragram.enums import StrategyType, TradeMode
from botragram.models import Position


@dataclass(slots=True, kw_only=True)
class _StoredPositions:
    async def get_open_positions(self) -> Sequence[Position]:
        return ()


@dataclass(slots=True, kw_only=True)
class _LivePositions:
    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        del synchronize
        return ()


@dataclass(slots=True)
class _HomeMenuPublisher:
    refreshed: bool = False

    async def publish_home_menu_refresh(self) -> None:
        self.refreshed = True


def _switch_service() -> tuple[MarketTypeSwitchService, RuntimeRestartCoordinator]:
    coordinator = RuntimeRestartCoordinator()
    service = MarketTypeSwitchService(
        trade_mode=TradeMode.PAPER,
        runtime_control=TradingRuntimeControl(),
        position_repository=_StoredPositions(),
        position_service=_LivePositions(),
        restart_coordinator=coordinator,
        settings=Settings(),
    )
    return service, coordinator


@pytest.mark.asyncio
async def test_strategy_switch_rejects_removed_strategy() -> None:
    """Do not stage a restart for a legacy strategy identifier."""
    service, coordinator = _switch_service()
    with pytest.raises(ValueError, match="Only PIER"):
        await service.prepare_strategy(strategy_type=StrategyType.EMA_SCALPING)
    assert coordinator.consume() is None


@pytest.mark.asyncio
async def test_selecting_active_pier_is_a_noop() -> None:
    """Keep the sole active strategy without creating a restart target."""
    service, coordinator = _switch_service()
    assert service.current_strategy_type is StrategyType.PINBAR_ENGULFING_EMA_RSI
    assert not await service.prepare_strategy(
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI
    )
    assert coordinator.consume() is None


@pytest.mark.asyncio
async def test_strategy_restart_session_remains_paused() -> None:
    """Require explicit operator resume after a strategy session rebuild."""
    runtime_control = TradingRuntimeControl()
    runtime_control.resume_global_cycle()
    publisher = _HomeMenuPublisher()

    await prepare_restarted_runtime_session(
        restart_target=StrategyType.PINBAR_ENGULFING_EMA_RSI,
        runtime_control=runtime_control,
        home_menu_publisher=publisher,
    )

    assert runtime_control.is_paused
    assert publisher.refreshed
