"""Guarded in-process runtime reconfiguration coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.app.settings_manager import SettingsManager
from botragram.config import Settings
from botragram.enums import ExecutionPolicy, MarketType, StrategyType, TradeMode
from botragram.exceptions import ExecutionPolicySwitchBlockedError
from botragram.models import Position

__all__ = [
    "MarketTypeSwitchService",
    "RuntimeRestartCoordinator",
    "RuntimeRestartTarget",
    "prepare_restarted_runtime_session",
    "run_until_restart",
]

type RuntimeRestartTarget = MarketType | ExecutionPolicy | StrategyType


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


class _IncompleteSubmissionProvider(Protocol):
    """Read LIVE submission attempts that still require recovery."""

    async def get_incomplete(self) -> Sequence[object]:
        """Return durable attempts that still block a workflow switch."""
        ...


class _StoppableRunner(Protocol):
    """Run until an explicit graceful stop request."""

    async def run(self) -> None:
        """Run the owned application loop."""
        ...

    def stop(self) -> None:
        """Request graceful loop termination."""
        ...


class _PersistentHomeMenuPublisher(Protocol):
    """Publish the persistent Telegram menu for the initialized session."""

    async def publish_home_menu_refresh(self) -> None:
        """Publish the current mode-aware persistent home menu."""
        ...


@dataclass(slots=True, kw_only=True)
class RuntimeRestartCoordinator:
    """Coordinate one validated in-process runtime-session restart request."""

    _requested_target: RuntimeRestartTarget | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _restart_event: asyncio.Event = field(
        default_factory=asyncio.Event,
        init=False,
        repr=False,
    )

    @staticmethod
    def _resolve_target(
        *,
        market_type: MarketType | None,
        execution_policy: ExecutionPolicy | None,
        strategy_type: StrategyType | None,
    ) -> RuntimeRestartTarget:
        targets = tuple(
            target
            for target in (market_type, execution_policy, strategy_type)
            if target is not None
        )
        if len(targets) != 1:
            raise ValueError("Exactly one runtime restart target is required")
        return targets[0]

    def stage(
        self,
        *,
        market_type: MarketType | None = None,
        execution_policy: ExecutionPolicy | None = None,
        strategy_type: StrategyType | None = None,
    ) -> None:
        """Stage one validated target before Telegram acknowledges the request."""
        if self._requested_target is not None or self._restart_event.is_set():
            raise RuntimeError("A runtime-session restart is already staged")
        self._requested_target = self._resolve_target(
            market_type=market_type,
            execution_policy=execution_policy,
            strategy_type=strategy_type,
        )

    def commit(
        self,
        *,
        market_type: MarketType | None = None,
        execution_policy: ExecutionPolicy | None = None,
        strategy_type: StrategyType | None = None,
    ) -> None:
        """Commit the exact staged target and wake the application session."""
        target = self._resolve_target(
            market_type=market_type,
            execution_policy=execution_policy,
            strategy_type=strategy_type,
        )
        if self._requested_target is not target:
            raise RuntimeError("Runtime restart request is not staged")
        self._restart_event.set()

    @property
    def has_committed_restart(self) -> bool:
        """Return whether a validated restart is waiting to be consumed."""
        return self._restart_event.is_set()

    async def wait(self) -> RuntimeRestartTarget:
        """Wait until Telegram commits one runtime-session restart request."""
        await self._restart_event.wait()
        requested = self._requested_target
        if requested is None:
            raise RuntimeError("Committed restart has no target")
        return requested

    def consume(self) -> RuntimeRestartTarget | None:
        """Return and clear the committed target after session shutdown."""
        if not self._restart_event.is_set():
            return None
        requested = self._requested_target
        self._requested_target = None
        self._restart_event.clear()
        return requested


async def run_until_restart(
    *,
    runner: _StoppableRunner,
    restart_coordinator: RuntimeRestartCoordinator,
) -> None:
    """Run trading until completion or a committed in-process restart."""
    runner_task = asyncio.create_task(
        runner.run(),
        name="botragram-trading-runner",
    )
    restart_task = asyncio.create_task(
        restart_coordinator.wait(),
        name="botragram-runtime-session-restart",
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


async def prepare_restarted_runtime_session(
    *,
    restart_target: RuntimeRestartTarget | None,
    runtime_control: TradingRuntimeControl,
    home_menu_publisher: _PersistentHomeMenuPublisher,
) -> None:
    """Apply post-initialization behavior for one completed soft restart."""
    if not isinstance(restart_target, (ExecutionPolicy, StrategyType)):
        return

    runtime_control.pause()
    await home_menu_publisher.publish_home_menu_refresh()


@dataclass(slots=True, kw_only=True)
class MarketTypeSwitchService:
    """Validate safe connector, workflow, and strategy session replacements."""

    trade_mode: TradeMode
    runtime_control: TradingRuntimeControl
    position_repository: _StoredPositionProvider
    position_service: _LivePositionProvider
    restart_coordinator: RuntimeRestartCoordinator
    settings: Settings | None = None
    submission_attempt_repository: _IncompleteSubmissionProvider | None = None

    async def _get_positions(self) -> Sequence[Position]:
        """Return the authoritative position view for the active trade mode."""
        return (
            await self.position_repository.get_open_positions()
            if self.trade_mode is TradeMode.PAPER
            else await self.position_service.get_all(synchronize=True)
        )

    async def prepare(self, *, market_type: MarketType) -> bool:
        """Validate and stage a Spot or Futures switch without restarting yet."""
        if market_type is self.runtime_control.market_type:
            self.runtime_control.confirm_market_type(market_type)
            return False

        self.runtime_control.require_configuration_change_allowed()
        if await self._get_positions():
            raise RuntimeError(
                "Close every active position before switching Spot or Futures"
            )

        self.restart_coordinator.stage(market_type=market_type)
        return True

    def commit(self, *, market_type: MarketType) -> None:
        """Commit a prepared product switch after Telegram acknowledgement."""
        self.restart_coordinator.commit(market_type=market_type)

    @property
    def current_execution_policy(self) -> ExecutionPolicy:
        """Return the execution workflow owned by the current session."""
        settings = self.settings
        if settings is None:
            return ExecutionPolicy.SINGLE_SYMBOL
        return settings.app.effective_execution_policy

    def available_execution_policies(self) -> tuple[ExecutionPolicy, ...]:
        """Return policies valid inside the immutable boot capability envelope."""
        settings = self.settings
        if settings is None:
            return (self.current_execution_policy,)

        available: list[ExecutionPolicy] = []
        for policy in ExecutionPolicy:
            candidate = self._settings_for_policy(policy=policy)
            try:
                SettingsManager.validate(settings=candidate)
            except ValueError:
                continue
            available.append(policy)
        return tuple(available)

    async def prepare_execution_policy(
        self,
        *,
        execution_policy: ExecutionPolicy,
        allow_operator_exit: bool = False,
    ) -> bool:
        """Validate and stage a safe execution-policy session replacement."""
        if self.settings is None:
            raise RuntimeError("Execution-policy switching is unavailable")

        if execution_policy is self.current_execution_policy:
            return False

        candidate = self._settings_for_policy(policy=execution_policy)
        try:
            SettingsManager.validate(settings=candidate)
        except ValueError as error:
            raise ExecutionPolicySwitchBlockedError(
                "Target trading mode is outside the boot capability envelope"
            ) from error
        await self._require_safe_session_replacement(
            blocked_message="Close every active position before switching trading mode",
            allow_operator_exit=allow_operator_exit,
        )

        try:
            self.restart_coordinator.stage(execution_policy=execution_policy)
        except RuntimeError as error:
            raise ExecutionPolicySwitchBlockedError(str(error)) from error
        return True

    def commit_execution_policy(
        self,
        *,
        execution_policy: ExecutionPolicy,
    ) -> None:
        """Commit an already-validated execution-policy session replacement."""
        self.restart_coordinator.commit(execution_policy=execution_policy)

    @property
    def current_strategy_type(self) -> StrategyType:
        """Return the immutable strategy owned by the current runtime session."""
        settings = self.settings
        if settings is None:
            return self.runtime_control.strategy_type
        return settings.strategy.strategy_type

    async def prepare_strategy(self, *, strategy_type: StrategyType) -> bool:
        """Validate and stage a strategy replacement for a fresh runtime session."""
        if self.settings is None:
            raise RuntimeError("Strategy switching is unavailable")
        if strategy_type is self.current_strategy_type:
            return False

        candidate = replace(
            self.settings,
            strategy=replace(
                self.settings.strategy,
                strategy_type=strategy_type,
            ),
        )
        SettingsManager.validate(settings=candidate)
        await self._require_safe_session_replacement(
            blocked_message="Close every active position before switching strategy",
        )
        self.restart_coordinator.stage(strategy_type=strategy_type)
        return True

    def commit_strategy(self, *, strategy_type: StrategyType) -> None:
        """Commit an already-validated strategy session replacement."""
        self.restart_coordinator.commit(strategy_type=strategy_type)

    async def _require_safe_session_replacement(
        self,
        *,
        blocked_message: str,
        allow_operator_exit: bool = False,
    ) -> None:
        """Require a flat, paused, recovery-clean boundary before rebuilding."""
        positions = await self._get_positions()
        if positions:
            raise ExecutionPolicySwitchBlockedError(
                blocked_message,
                active_position_count=len(positions),
            )

        try:
            self.runtime_control.require_configuration_change_allowed(
                allow_operator_exit=allow_operator_exit,
            )
        except RuntimeError as error:
            raise ExecutionPolicySwitchBlockedError(str(error)) from error

        if self.trade_mode is not TradeMode.LIVE:
            return
        if self.runtime_control.runtime_contexts:
            raise ExecutionPolicySwitchBlockedError(
                "LIVE runtime contexts must be fully reconciled before switching"
            )
        if not self.runtime_control.is_position_protection_ready:
            raise ExecutionPolicySwitchBlockedError(
                "LIVE recovery/protection must be READY before switching"
            )
        repository = self.submission_attempt_repository
        if repository is None:
            raise RuntimeError("LIVE submission recovery state is unavailable")
        if await repository.get_incomplete():
            raise ExecutionPolicySwitchBlockedError(
                "Incomplete LIVE submission recovery blocks runtime switch"
            )

    def _settings_for_policy(self, *, policy: ExecutionPolicy) -> Settings:
        """Build one immutable candidate without widening boot authorization."""
        settings = self.settings
        if settings is None:
            raise RuntimeError("Execution-policy switching is unavailable")
        return replace(
            settings,
            app=replace(
                settings.app,
                execution_policy=policy,
                autonomous_execution_enabled=False,
            ),
        )
