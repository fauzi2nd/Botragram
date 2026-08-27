"""Bounded in-process autonomous LIVE recovery tests."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app import AutonomousLiveCycleUnsafeError, TradingRunner
from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import (
    Interval,
    LiveMarketStreamLifecycleStatus,
    LiveRuntimeHealthReason,
    LiveRuntimeHealthStatus,
    OrderType,
    SignalType,
    StrategyType,
    TradeMode,
)
from botragram.models import (
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveProtectionMonitorState,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimeHealthSnapshot,
    LiveRuntimePositionContext,
    Signal,
    TradingDecision,
    TradingResult,
)
from botragram.utils.retry import CappedExponentialBackoff

_NOW = datetime(2026, 8, 21, tzinfo=UTC)
_CONTEXT = LiveRuntimePositionContext(
    symbol="BTCUSDT",
    interval=Interval.M15,
    strategy_type=StrategyType.EMA_SCALPING,
)


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
    connectivity_failures_remaining: int = 0
    failure_sequence: list[Exception] = field(default_factory=list[Exception])
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
        if self.failure_sequence:
            raise self.failure_sequence.pop(0)
        if self.connectivity_failures_remaining > 0:
            self.connectivity_failures_remaining -= 1
            raise ConnectionError("temporary Binance outage")
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
    on_success: Callable[[], None] | None = None
    clear_contexts_on_failure: bool = False
    calls: int = 0
    activation_requests: list[bool] = field(default_factory=list[bool])
    completed: asyncio.Event = field(default_factory=asyncio.Event)

    async def recover(self, *, activate_runtime: bool = True) -> bool:
        self.calls += 1
        self.activation_requests.append(activate_runtime)
        if self.failure is not None:
            raise self.failure
        if not self.outcomes:
            raise RuntimeError("Unexpected extra recovery attempt")
        outcome = self.outcomes.pop(0)
        if not outcome and self.clear_contexts_on_failure:
            self.control.clear_runtime_contexts()
        if outcome and self.on_success is not None:
            self.on_success()
        if outcome and self.resume_on_success and activate_runtime:
            self.control.set_position_protection_ready(True)
            self.control.resume_global_cycle()
        elif outcome:
            self.control.set_position_protection_ready(True)
        self.completed.set()
        return outcome


@dataclass(slots=True, kw_only=True)
class _HealthProvider:
    control: TradingRuntimeControl
    status: LiveRuntimeHealthStatus
    reason: LiveRuntimeHealthReason | None
    authorization_present: bool = True
    authorization_exact: bool = True
    calls: int = 0

    def set_active(self) -> None:
        if self.control.is_paused:
            self.set_ready_while_paused()
        else:
            self.status = LiveRuntimeHealthStatus.ACTIVE
            self.reason = None

    def set_degraded(self) -> None:
        self.status = LiveRuntimeHealthStatus.DEGRADED
        self.reason = LiveRuntimeHealthReason.STREAM_FAILED

    def set_private_pending(self) -> None:
        self.status = LiveRuntimeHealthStatus.DEGRADED
        self.reason = LiveRuntimeHealthReason.USER_DATA_STREAM_NOT_READY

    def set_ready_while_paused(self) -> None:
        self.status = LiveRuntimeHealthStatus.PAUSED
        self.reason = LiveRuntimeHealthReason.RUNNER_PAUSED

    def set_inactive(self) -> None:
        self.status = LiveRuntimeHealthStatus.INACTIVE
        self.reason = LiveRuntimeHealthReason.NO_POSITIONS

    def get_snapshot(self) -> LiveRuntimeHealthSnapshot:
        self.calls += 1
        contexts = self.control.runtime_contexts
        status = self.status
        reason = self.reason
        if (
            status is LiveRuntimeHealthStatus.PAUSED
            and reason is LiveRuntimeHealthReason.RUNNER_PAUSED
            and not self.control.is_paused
        ):
            status = LiveRuntimeHealthStatus.ACTIVE
            reason = None
        stream_failed = reason is LiveRuntimeHealthReason.STREAM_FAILED
        return LiveRuntimeHealthSnapshot(
            status=status,
            reason=reason,
            contexts=contexts,
            affected_contexts=(
                contexts
                if status
                in {
                    LiveRuntimeHealthStatus.DEGRADED,
                    LiveRuntimeHealthStatus.BLOCKED,
                }
                else ()
            ),
            authorization_present=self.authorization_present,
            authorization_exact=self.authorization_exact,
            runner_paused=self.control.is_paused,
            cycle_in_progress=self.control.cycle_in_progress,
            stream_states=(
                LiveMarketStreamState(
                    identity=LiveMarketStreamIdentity.from_runtime_context(
                        context=_CONTEXT
                    ),
                    lifecycle_status=(
                        LiveMarketStreamLifecycleStatus.FAILED
                        if stream_failed
                        else LiveMarketStreamLifecycleStatus.RUNNING
                    ),
                    first_tick_received=not stream_failed,
                    event_count=1,
                    last_price=Decimal("100"),
                    last_event_monotonic=1.0,
                    failure_type="RuntimeError" if stream_failed else None,
                ),
            ),
            monitor_states=(
                LiveProtectionMonitorState(
                    context=_CONTEXT,
                    is_active=True,
                    failure_type=None,
                ),
            ),
        )


def _active_control() -> TradingRuntimeControl:
    control = TradingRuntimeControl()
    control.resume_global_cycle()
    return control


def _active_recovered_control() -> TradingRuntimeControl:
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=(_CONTEXT,))
    control.set_live_management_authorization(
        authorization=LiveRecoveredPositionManagementAuthorization(
            contexts=(_CONTEXT,),
            runtime_management_allowed=True,
        ),
    )
    control.set_position_protection_ready(True)
    control.resume_global_cycle()
    return control


def _runner(
    *,
    executor: _GlobalExecutor,
    control: TradingRuntimeControl,
    recovery: _RecoveryProvider | None,
    health: _HealthProvider | None = None,
    trade_mode: TradeMode = TradeMode.LIVE,
    maximum_recovery_attempts: int = 1,
    cycle_interval_seconds: float = 0.05,
    health_check_interval_seconds: float = 0.005,
    heartbeat_interval_seconds: float = 60.0,
    unattended_recovery_delay_seconds: float = 0.001,
) -> TradingRunner:
    return TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        trade_mode=trade_mode,
        runtime_control=control,
        autonomous_live_recovery_provider=recovery,
        live_runtime_health_provider=health,
        maximum_autonomous_live_recovery_attempts=maximum_recovery_attempts,
        autonomous_live_health_check_interval_seconds=health_check_interval_seconds,
        cycle_interval_seconds=cycle_interval_seconds,
        failure_retry_delay_seconds=0.001,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        unattended_recovery_backoff=CappedExponentialBackoff(
            initial_delay_seconds=unattended_recovery_delay_seconds,
            maximum_delay_seconds=unattended_recovery_delay_seconds,
            jitter_ratio=0.0,
            random_source=lambda: 0.5,
        ),
    )


async def _wait_for_recovery_calls(
    *,
    recovery: _RecoveryProvider,
    expected: int,
) -> None:
    """Wait deterministically for an unattended recovery attempt count."""
    async with asyncio.timeout(1.0):
        while recovery.calls < expected:
            await asyncio.sleep(0)


def test_one_operational_recovery_resumes_with_a_fresh_global_cycle() -> None:
    asyncio.run(_run_one_operational_recovery_test())


async def _run_one_operational_recovery_test() -> None:
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


def test_repeated_unsafe_outcomes_do_not_exhaust_recovery_budget() -> None:
    asyncio.run(_run_repeated_unsafe_outcome_recovery_test())


async def _run_repeated_unsafe_outcome_recovery_test() -> None:
    control = _active_control()
    executor = _GlobalExecutor(unsafe_failures_remaining=2)
    recovery = _RecoveryProvider(control=control, outcomes=[True, True])
    runner = _runner(executor=executor, control=control, recovery=recovery)
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(executor.successful_execution.wait(), timeout=1.0)
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert executor.calls == 3
    assert recovery.calls == 2
    assert not control.is_paused


def test_recovery_retries_indefinitely_until_it_eventually_succeeds() -> None:
    asyncio.run(_run_eventual_recovery_test())


async def _run_eventual_recovery_test() -> None:
    control = _active_control()
    executor = _GlobalExecutor(unsafe_failures_remaining=1)
    recovery = _RecoveryProvider(
        control=control,
        outcomes=[False, False, False, False],
    )
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        unattended_recovery_delay_seconds=0.02,
    )
    task = asyncio.create_task(runner.run())

    await _wait_for_recovery_calls(recovery=recovery, expected=3)

    assert not task.done()
    assert executor.calls == 1
    assert control.is_paused

    recovery.outcomes.append(True)
    await asyncio.wait_for(executor.successful_execution.wait(), timeout=1.0)
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert executor.calls == 2
    assert recovery.calls == 5
    assert not control.is_paused


def test_recovery_success_must_actively_resume_runtime() -> None:
    asyncio.run(_run_false_success_recovery_test())


async def _run_false_success_recovery_test() -> None:
    control = _active_control()
    executor = _GlobalExecutor(unsafe_failures_remaining=1)
    recovery = _RecoveryProvider(
        control=control,
        outcomes=[True, True, True, True],
        resume_on_success=False,
    )
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        unattended_recovery_delay_seconds=0.02,
    )
    task = asyncio.create_task(runner.run())
    await _wait_for_recovery_calls(recovery=recovery, expected=3)
    assert not task.done()
    assert executor.calls == 1
    assert control.is_paused
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)


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


def test_degraded_runtime_health_recovers_before_fresh_global_cycle() -> None:
    asyncio.run(_run_degraded_runtime_health_recovery_test())


async def _run_degraded_runtime_health_recovery_test() -> None:
    control = _active_recovered_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.DEGRADED,
        reason=LiveRuntimeHealthReason.STREAM_FAILED,
    )
    executor = _GlobalExecutor(unsafe_failures_remaining=0)
    recovery = _RecoveryProvider(
        control=control,
        outcomes=[True],
        on_success=health.set_active,
    )
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
    )

    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(recovery.completed.wait(), timeout=1.0)
    await asyncio.wait_for(executor.successful_execution.wait(), timeout=1.0)
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert executor.calls == 1
    assert recovery.calls == 1
    assert not control.is_paused


def test_blocked_runtime_health_never_consumes_automatic_recovery() -> None:
    asyncio.run(_run_blocked_runtime_health_test())


async def _run_blocked_runtime_health_test() -> None:
    control = _active_recovered_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.BLOCKED,
        reason=LiveRuntimeHealthReason.RECONCILIATION_REQUIRED,
    )
    executor = _GlobalExecutor(unsafe_failures_remaining=0)
    recovery = _RecoveryProvider(control=control, outcomes=[True])
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
    )

    await asyncio.wait_for(runner.run(), timeout=1.0)

    assert executor.calls == 0
    assert recovery.calls == 0
    assert control.is_paused


@pytest.mark.parametrize(
    ("authorization_present", "authorization_exact"),
    (
        (False, False),
        (True, False),
    ),
)
def test_degraded_health_requires_exact_management_authorization(
    authorization_present: bool,
    authorization_exact: bool,
) -> None:
    asyncio.run(
        _run_degraded_health_without_exact_authorization_test(
            authorization_present=authorization_present,
            authorization_exact=authorization_exact,
        )
    )


async def _run_degraded_health_without_exact_authorization_test(
    *,
    authorization_present: bool,
    authorization_exact: bool,
) -> None:
    control = _active_recovered_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.DEGRADED,
        reason=LiveRuntimeHealthReason.STREAM_FAILED,
        authorization_present=authorization_present,
        authorization_exact=authorization_exact,
    )
    executor = _GlobalExecutor(unsafe_failures_remaining=0)
    recovery = _RecoveryProvider(control=control, outcomes=[True])
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
    )

    await asyncio.wait_for(runner.run(), timeout=1.0)

    assert executor.calls == 0
    assert recovery.calls == 0
    assert control.is_paused


def test_runtime_health_degradation_wakes_global_cadence_wait() -> None:
    asyncio.run(_run_runtime_health_cadence_wakeup_test())


async def _run_runtime_health_cadence_wakeup_test() -> None:
    control = _active_recovered_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.ACTIVE,
        reason=None,
    )
    executor = _GlobalExecutor(unsafe_failures_remaining=0)
    recovery = _RecoveryProvider(
        control=control,
        outcomes=[True],
        on_success=health.set_active,
    )
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
        cycle_interval_seconds=0.5,
        health_check_interval_seconds=0.005,
    )

    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(executor.successful_execution.wait(), timeout=1.0)
    assert executor.calls == 1

    health.set_degraded()
    await asyncio.wait_for(recovery.completed.wait(), timeout=0.2)
    async with asyncio.timeout(1.0):
        while executor.calls < 2:
            await asyncio.sleep(0)

    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert executor.calls == 2
    assert recovery.calls == 1


def test_connectivity_health_recovery_does_not_consume_safety_budget() -> None:
    """Retry dependency health separately after one bounded safety recovery."""
    asyncio.run(_run_independent_connectivity_recovery_budget_test())


async def _run_independent_connectivity_recovery_budget_test() -> None:
    control = _active_recovered_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.ACTIVE,
        reason=None,
    )
    executor = _GlobalExecutor(unsafe_failures_remaining=1)
    recovery = _RecoveryProvider(
        control=control,
        outcomes=[True, True],
    )

    def update_health_after_recovery() -> None:
        if recovery.calls == 1:
            health.set_degraded()
        else:
            health.set_active()

    recovery.on_success = update_health_after_recovery
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
    )

    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(executor.successful_execution.wait(), timeout=1.0)
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert executor.calls == 2
    assert recovery.calls == 2
    assert recovery.activation_requests == [True, False]
    assert not control.is_paused


def test_reconciliation_outage_survives_after_safety_budget_was_used() -> None:
    """Keep DNS recovery unbounded and paused after one bounded safety recovery."""
    asyncio.run(_run_reconciliation_outage_after_safety_recovery_test())


async def _run_reconciliation_outage_after_safety_recovery_test() -> None:
    control = _active_recovered_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.ACTIVE,
        reason=None,
    )
    executor = _GlobalExecutor(
        unsafe_failures_remaining=0,
        failure_sequence=[
            AutonomousLiveCycleUnsafeError("configured safety failure"),
            ConnectionError("configured reconciliation DNS outage"),
        ],
    )
    recovery = _RecoveryProvider(
        control=control,
        outcomes=[True, False, False, False],
        on_success=health.set_active,
    )
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
        unattended_recovery_delay_seconds=0.02,
    )
    task = asyncio.create_task(runner.run())

    await _wait_for_recovery_calls(recovery=recovery, expected=3)

    assert not task.done()
    assert control.is_paused
    assert executor.calls == 2
    assert recovery.activation_requests == [True, False, False]

    recovery.outcomes.append(True)
    await asyncio.wait_for(executor.successful_execution.wait(), timeout=1.0)
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert executor.calls == 3
    assert recovery.calls == 5
    assert recovery.activation_requests == [True, False, False, False, False]
    assert not control.is_paused


def test_health_check_interval_must_be_positive() -> None:
    control = TradingRuntimeControl()
    executor = _GlobalExecutor(unsafe_failures_remaining=0)
    with pytest.raises(ValueError, match="health check interval"):
        _runner(
            executor=executor,
            control=control,
            recovery=None,
            health_check_interval_seconds=0,
        )


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


def test_prolonged_connectivity_outage_stays_paused_then_recovers() -> None:
    """Keep the process alive and avoid fresh cycles until authoritative recovery."""
    asyncio.run(_run_prolonged_connectivity_outage_test())


async def _run_prolonged_connectivity_outage_test() -> None:
    control = _active_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.INACTIVE,
        reason=LiveRuntimeHealthReason.NO_POSITIONS,
        authorization_present=False,
        authorization_exact=False,
    )
    executor = _GlobalExecutor(
        unsafe_failures_remaining=0,
        connectivity_failures_remaining=1,
    )
    recovery = _RecoveryProvider(control=control, outcomes=[False, False])
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
    )
    task = asyncio.create_task(runner.run())

    await _wait_for_recovery_calls(recovery=recovery, expected=2)

    assert not task.done()
    assert control.is_paused
    assert executor.calls == 1

    recovery.outcomes.append(True)
    await asyncio.wait_for(executor.successful_execution.wait(), timeout=1.0)
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert recovery.calls == 3
    assert executor.calls == 2
    assert not control.is_paused


def test_stale_private_stream_recovers_before_any_new_cycle() -> None:
    """Block fresh entry work while private-stream health is non-authoritative."""
    asyncio.run(_run_stale_private_stream_health_test())


async def _run_stale_private_stream_health_test() -> None:
    control = _active_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.DEGRADED,
        reason=LiveRuntimeHealthReason.USER_DATA_STREAM_NOT_READY,
        authorization_present=False,
        authorization_exact=False,
    )
    executor = _GlobalExecutor(unsafe_failures_remaining=0)
    recovery = _RecoveryProvider(
        control=control,
        outcomes=[True],
    )
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
    )
    task = asyncio.create_task(runner.run())

    async with asyncio.timeout(1.0):
        while not control.is_paused:
            await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    assert executor.calls == 0
    assert recovery.calls == 0
    assert control.is_paused

    health.set_inactive()
    await asyncio.wait_for(executor.successful_execution.wait(), timeout=1.0)
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert recovery.calls == 1
    assert executor.calls == 1


def test_rest_recovery_waits_for_private_stream_in_one_episode(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not claim convergence or rerun REST recovery before private READY."""
    asyncio.run(_run_rest_before_private_stream_test(caplog=caplog))


async def _run_rest_before_private_stream_test(
    *,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="botragram.app.trading_runner")
    control = _active_recovered_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.DEGRADED,
        reason=LiveRuntimeHealthReason.STREAM_FAILED,
    )
    executor = _GlobalExecutor(unsafe_failures_remaining=0)
    recovery = _RecoveryProvider(control=control, outcomes=[True, True])

    def advance_health() -> None:
        if recovery.calls == 1:
            health.set_private_pending()
        else:
            health.set_active()

    recovery.on_success = advance_health
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
    )
    task = asyncio.create_task(runner.run())

    await _wait_for_recovery_calls(recovery=recovery, expected=1)
    async with asyncio.timeout(1.0):
        while not control.is_paused:
            await asyncio.sleep(0)
    await asyncio.sleep(0.01)

    assert not task.done()
    assert recovery.calls == 1
    assert executor.calls == 0
    assert control.is_paused
    assert _count_log(caplog=caplog, text="paused for unattended recovery") == 1
    assert _count_log(caplog=caplog, text="restored authoritative state") == 0

    health.set_ready_while_paused()
    await asyncio.wait_for(executor.successful_execution.wait(), timeout=1.0)
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert recovery.calls == 2
    assert recovery.activation_requests == [False, False]
    assert executor.calls == 1
    assert not control.is_paused
    assert _count_log(caplog=caplog, text="paused for unattended recovery") == 1
    assert _count_log(caplog=caplog, text="restored authoritative state") == 1


def test_outage_heartbeat_preserves_known_position_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retain pre-outage contexts after a failed recovery clears local state."""
    asyncio.run(_run_known_position_heartbeat_test(caplog=caplog))


async def _run_known_position_heartbeat_test(
    *,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="botragram.app.trading_runner")
    control = _active_recovered_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.ACTIVE,
        reason=None,
    )
    executor = _GlobalExecutor(
        unsafe_failures_remaining=0,
        connectivity_failures_remaining=1,
    )
    recovery = _RecoveryProvider(
        control=control,
        outcomes=[False],
        clear_contexts_on_failure=True,
    )
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
        heartbeat_interval_seconds=0.001,
        unattended_recovery_delay_seconds=0.05,
    )
    task = asyncio.create_task(runner.run())

    await _wait_for_recovery_calls(recovery=recovery, expected=1)
    async with asyncio.timeout(1.0):
        while (
            _count_log(
                caplog=caplog,
                text="positions_state=known_non_authoritative",
            )
            == 0
        ):
            await asyncio.sleep(0)

    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert recovery.calls == 1
    assert not control.runtime_contexts
    assert _count_log(caplog=caplog, text="positions_known=1") >= 1


def test_explicit_stop_while_private_recovery_is_pending() -> None:
    """Stop cleanly without REST recovery or a fresh entry while private is stale."""
    asyncio.run(_run_explicit_stop_during_private_recovery_test())


async def _run_explicit_stop_during_private_recovery_test() -> None:
    control = _active_recovered_control()
    health = _HealthProvider(
        control=control,
        status=LiveRuntimeHealthStatus.DEGRADED,
        reason=LiveRuntimeHealthReason.USER_DATA_STREAM_NOT_READY,
    )
    executor = _GlobalExecutor(unsafe_failures_remaining=0)
    recovery = _RecoveryProvider(control=control, outcomes=[True])
    runner = _runner(
        executor=executor,
        control=control,
        recovery=recovery,
        health=health,
    )
    task = asyncio.create_task(runner.run())

    async with asyncio.timeout(1.0):
        while not control.is_paused:
            await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert not runner.is_running
    assert control.is_paused
    assert recovery.calls == 0
    assert executor.calls == 0


def _count_log(
    *,
    caplog: pytest.LogCaptureFixture,
    text: str,
) -> int:
    """Return the number of captured recovery messages containing text."""
    return sum(text in record.getMessage() for record in caplog.records)
