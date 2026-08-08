"""
Botragram

Description:
    Guarded runtime coordination for switching exchange product families.

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
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import MarketType, TradeMode
from botragram.models import Position

__all__ = [
    "MarketTypeSwitchService",
    "RuntimeRestartCoordinator",
    "run_until_restart",
]


# =============================================================================
# Dependency Contracts
# =============================================================================
class _StoredPositionProvider(Protocol):
    """Read persistent open positions without exchange synchronization."""

    async def get_open_positions(self) -> Sequence[Position]:
        """Return active stored positions."""
        ...


class _LivePositionProvider(Protocol):
    """Read positions with optional exchange synchronization."""

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        """Return active exchange positions."""
        ...


class _StoppableRunner(Protocol):
    """Run until an explicit graceful stop request."""

    async def run(self) -> None:
        """Run the owned application loop."""
        ...

    def stop(self) -> None:
        """Request graceful loop termination."""
        ...


# =============================================================================
# Restart Coordination
# =============================================================================
@dataclass(slots=True, kw_only=True)
class RuntimeRestartCoordinator:
    """Coordinate one committed in-process product restart request."""

    _requested_market_type: MarketType | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _restart_event: asyncio.Event = field(
        default_factory=asyncio.Event,
        init=False,
        repr=False,
    )

    def stage(self, *, market_type: MarketType) -> None:
        """Stage a validated target before Telegram acknowledges the request."""
        if self._restart_event.is_set():
            raise RuntimeError("A market-type restart is already committed")

        self._requested_market_type = market_type

    def commit(self, *, market_type: MarketType) -> None:
        """Commit the staged target and wake the application session."""
        if self._requested_market_type is not market_type:
            raise RuntimeError("Market-type restart request is not staged")

        self._restart_event.set()

    async def wait(self) -> MarketType:
        """Wait until Telegram commits a product restart request."""
        await self._restart_event.wait()
        requested = self._requested_market_type

        if requested is None:
            raise RuntimeError("Committed restart has no market type")

        return requested

    def consume(self) -> MarketType | None:
        """Return and clear the committed target after session shutdown."""
        if not self._restart_event.is_set():
            return None

        requested = self._requested_market_type
        self._requested_market_type = None
        self._restart_event.clear()
        return requested


async def run_until_restart(
    *,
    runner: _StoppableRunner,
    restart_coordinator: RuntimeRestartCoordinator,
) -> None:
    """Run trading until completion or a committed connector restart."""
    runner_task = asyncio.create_task(
        runner.run(),
        name="botragram-trading-runner",
    )
    restart_task = asyncio.create_task(
        restart_coordinator.wait(),
        name="botragram-market-type-restart",
    )

    try:
        done, _ = await asyncio.wait(
            (runner_task, restart_task),
            return_when=asyncio.FIRST_COMPLETED,
        )

        if restart_task in done:
            runner.stop()

        await runner_task
    finally:
        for task in (runner_task, restart_task):
            if not task.done():
                task.cancel()

        await asyncio.gather(
            runner_task,
            restart_task,
            return_exceptions=True,
        )


# =============================================================================
# Product Switch Service
# =============================================================================
@dataclass(slots=True, kw_only=True)
class MarketTypeSwitchService:
    """Validate and stage a safe Spot or Futures connector restart."""

    trade_mode: TradeMode
    runtime_control: TradingRuntimeControl
    position_repository: _StoredPositionProvider
    position_service: _LivePositionProvider
    restart_coordinator: RuntimeRestartCoordinator

    async def prepare(self, *, market_type: MarketType) -> bool:
        """Validate and stage a product switch without restarting yet."""
        if market_type is self.runtime_control.market_type:
            self.runtime_control.confirm_market_type(market_type)
            return False

        self.runtime_control.require_configuration_change_allowed()
        positions = (
            await self.position_repository.get_open_positions()
            if self.trade_mode is TradeMode.PAPER
            else await self.position_service.get_all(synchronize=True)
        )

        if positions:
            raise RuntimeError(
                "Close every active position before switching Spot or Futures"
            )

        self.restart_coordinator.stage(market_type=market_type)
        return True

    def commit(self, *, market_type: MarketType) -> None:
        """Commit a prepared switch after Telegram sends confirmation."""
        self.restart_coordinator.commit(market_type=market_type)
