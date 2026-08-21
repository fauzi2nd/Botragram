"""Bounded in-process autonomous LIVE recovery tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app import AutonomousLiveCycleUnsafeError, TradingRunner
from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import Interval, OrderType, SignalType, StrategyType, TradeMode
from botragram.models import (
    LiveRecoveredPositionManagementAuthorization,
    Signal,
    TradingDecision,
    TradingResult,
)

_NOW = datetime(2026, 8, 21, tzinfo=UTC)


def _safe_result() -> TradingResult:
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.HOLD,
        price=Decimal("100"),
        confidence=Decimal("0"),
        strategy_name="test",
        generated_at=_NOW,
    )
    decision = TradingDecision(
        should_execute=False,
        signal=signal,
        risk_result=None,
        reason="No executable signal",
    )
    return TradingResult(
        executed=False,
        decision=decision,
        order=None,
        reason=decision.reason,
    )


@dataclass(slots=True, kw_only=True)
class _GlobalExecutor:
    unsafe_failures_remaining: int
    result: TradingResult = field(default_factory=_safe_result)
    calls: int = 0
    successful_execution: asyncio.Event = field(default_factory=asyncio.Event)

    async def execute_global(
        self,
        *,
        interval: Interval,
        candle_limit: int,
    ) -> tuple[TradingResult, ...]:
        del interval, candle_limit
        self.calls += 1
        if self.unsafe_failures_remaining > 0:
            self.unsafe_failures_remaining -= 1
            raise AutonomousLiveCycleUnsafeError("configured unsafe LIVE outcome")
        self.successful_execution.set()
        return (self.result,)

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        strategy_type: StrategyType | None = None,
        live_management_authorization: (
            LiveRecoveredPositionManagementAuthorization | None
        ) = None,
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> tuple[TradingResult, ...]:
        del (
            symbol,
            strategy_type,
            live_management_authorization,
            current_drawdown_pct,
            order_type,
            price,
            account_balance_override,
            synchronize_position,
            submit_order,
        )
        return await self.execute_global(interval=interval, candle_limit=candle_limit)


@dataclass(slots=True, kw_only=True)
class _RecoveryProvider:
    control: TradingRuntimeControl
    outcomes: list[bool] = field(default_factory=list[bool])
    resume_on_success: bool = True
    failure: BaseException | None = None
    calls: int = 0
    completed: asyncio.Event = field(default_factory=asyncio.Event)

    async def recover(self) -> bool:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        if not self.outcomes:
            raise RuntimeError("Unexpected extra recovery attempt")
        outcome = self.outcomes.pop(0)
        if outcome and self.resume_on_success:
            self.control.set_position_protection_ready(True)
            self.control.resume_global_cycle()
        self.completed.set()
        return outcome


def _active_control() -> TradingRuntimeControl:
    control = TradingRuntimeControl()
    control.resume_global_cycle()
    return control


def _runner(
    *,
    executor: _GlobalExecutor,
    control: TradingRuntimeControl,
    recovery: _RecoveryProvider | None,
    trade_mode: TradeMode = TradeMode.LIVE,
    maximum_recovery_attempts: int = 1,
    cycle_interval_seconds: float = 0.05,
) -> TradingRunner:
    return TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        trade_mode=trade_mode,
        runtime_control=control,
        autonomous_live_recovery_provider=recovery,
        maximum_autonomous_live_recovery_attempts=maximum_recovery_attempts,
        cycle_interval_seconds=cycle_interval_seconds,
        failure_retry_delay_seconds=0.001,
        heartbeat_interval_seconds=60.0,
    )


def test_one_bounded_recovery_resumes_with_a_fresh_global_cycle() -> None:
    asyncio.run(_run_one_bounded_recovery_test())


async def _run_one_bounded_recovery_test() -> None:
    control = _active_control()
    executor = _GlobalExecutor(unsafe_failures_remaining=1)
    recovery = _RecoveryProvider(control=control, outcomes=[True])
    runner = _runner(executor=executor, control=control, recovery=recovery)
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(recovery.completed.wait(), timeout=1.0)
    await asyncio.sleep(0.005)
    assert executor.calls == 1
    await asyncio.wait_for(executor.successful_execution.wait(), timeout=1.0)
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert executor.calls == 2
    assert recovery.calls == 1
    assert not control.is_paused


def test_second_unsafe_outcome_exhausts_process_recovery_budget() -> None:
    asyncio.run(_run_recovery_budget_exhaustion_test())


async def _run_recovery_budget_exhaustion_test() -> None:
    control = _active_control()
    executor = _GlobalExecutor(unsafe_failures_remaining=2)
    recovery = _RecoveryProvider(control=control, outcomes=[True])
    runner = _runner(executor=executor, control=control, recovery=recovery)
    await asyncio.wait_for(runner.run(), timeout=1.0)
    assert executor.calls == 2
    assert recovery.calls == 1
    assert control.is_paused


def test_failed_recovery_remains_fail_closed_without_fresh_cycle() -> None:
    asyncio.run(_run_failed_recovery_test())


async def _run_failed_recovery_test() -> None:
    control = _active_control()
    executor = _GlobalExecutor(unsafe_failures_remaining=1)
    recovery = _RecoveryProvider(control=control, outcomes=[False])
    runner = _runner(executor=executor, control=control, recovery=recovery)
    await asyncio.wait_for(runner.run(), timeout=1.0)
    assert executor.calls == 1
    assert recovery.calls == 1
    assert control.is_paused


def test_recovery_success_must_actively_resume_runtime() -> None:
    asyncio.run(_run_false_success_recovery_test())


async def _run_false_success_recovery_test() -> None:
    control = _active_control()
    executor = _GlobalExecutor(unsafe_failures_remaining=1)
    recovery = _RecoveryProvider(
        control=control,
        outcomes=[True],
        resume_on_success=False,
    )
    runner = _runner(executor=executor, control=control, recovery=recovery)
    await asyncio.wait_for(runner.run(), timeout=1.0)
    assert executor.calls == 1
    assert recovery.calls == 1
    assert control.is_paused


def test_recovery_provider_is_rejected_outside_global_live_mode() -> None:
    asyncio.run(_run_non_live_recovery_rejection_test())


async def _run_non_live_recovery_rejection_test() -> None:
    control = _active_control()
    executor = _GlobalExecutor(unsafe_failures_remaining=1)
    recovery = _RecoveryProvider(control=control, outcomes=[True])
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        trade_mode=TradeMode.PAPER,
    )
    await asyncio.wait_for(runner.run(), timeout=1.0)
    assert executor.calls == 1
    assert recovery.calls == 0
    assert control.is_paused


def test_recovery_exception_remains_fail_closed() -> None:
    asyncio.run(_run_recovery_exception_test())


async def _run_recovery_exception_test() -> None:
    control = _active_control()
    executor = _GlobalExecutor(unsafe_failures_remaining=1)
    recovery = _RecoveryProvider(
        control=control,
        failure=RuntimeError("configured recovery failure"),
    )
    runner = _runner(executor=executor, control=control, recovery=recovery)
    await asyncio.wait_for(runner.run(), timeout=1.0)
    assert executor.calls == 1
    assert recovery.calls == 1
    assert control.is_paused


def test_recovery_cancellation_propagates_without_fresh_cycle() -> None:
    asyncio.run(_run_recovery_cancellation_test())


async def _run_recovery_cancellation_test() -> None:
    control = _active_control()
    executor = _GlobalExecutor(unsafe_failures_remaining=1)
    recovery = _RecoveryProvider(
        control=control,
        failure=asyncio.CancelledError(),
    )
    runner = _runner(executor=executor, control=control, recovery=recovery)

    with pytest.raises(asyncio.CancelledError):
        await runner.run()

    assert executor.calls == 1
    assert recovery.calls == 1
    assert control.is_paused


def test_recovery_budget_must_be_positive() -> None:
    control = TradingRuntimeControl()
    executor = _GlobalExecutor(unsafe_failures_remaining=0)
    with pytest.raises(ValueError, match="Maximum autonomous LIVE recovery attempts"):
        _runner(
            executor=executor,
            control=control,
            recovery=None,
            maximum_recovery_attempts=0,
        )
