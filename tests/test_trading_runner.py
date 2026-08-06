"""
Botragram

Description:
    Trading runtime orchestration and execution-safety tests.

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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import TradingRunner, TradingRuntimeControl
from botragram.enums import Interval, OrderType, SignalType, TradeMode
from botragram.models import Signal, TradingDecision, TradingResult

# =============================================================================
# Constants
# =============================================================================
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# =============================================================================
# Test Fakes
# =============================================================================
@dataclass(slots=True, frozen=True)
class ExecutionCall:
    """Captured trading workflow invocation."""

    symbol: str
    interval: Interval
    candle_limit: int
    account_balance_override: Decimal | None
    synchronize_position: bool
    submit_order: bool


@dataclass(slots=True, kw_only=True)
class FakeTradingCycleExecutor:
    """Record runner calls and return a deterministic result."""

    result: TradingResult
    failure: Exception | None = None
    failures_remaining: int | None = None
    calls: list[ExecutionCall] = field(default_factory=list[ExecutionCall])
    execution_started: asyncio.Event = field(default_factory=asyncio.Event)
    execution_succeeded: asyncio.Event = field(default_factory=asyncio.Event)

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> TradingResult:
        """Capture one complete executor invocation."""
        del current_drawdown_pct, order_type, price
        self.calls.append(
            ExecutionCall(
                symbol=symbol,
                interval=interval,
                candle_limit=candle_limit,
                account_balance_override=account_balance_override,
                synchronize_position=synchronize_position,
                submit_order=submit_order,
            )
        )
        self.execution_started.set()

        should_fail = self.failure is not None and (
            self.failures_remaining is None or self.failures_remaining > 0
        )

        if should_fail:
            if self.failures_remaining is not None:
                self.failures_remaining -= 1

            assert self.failure is not None
            raise self.failure

        self.execution_succeeded.set()
        return self.result


# =============================================================================
# Test Helpers
# =============================================================================
def _create_result(
    *,
    should_execute: bool = False,
    reason: str = "No executable signal",
) -> TradingResult:
    """Create a deterministic non-submitted trading result."""
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY if should_execute else SignalType.HOLD,
        price=Decimal("100"),
        confidence=Decimal("0.8"),
        strategy_name="test_strategy",
        generated_at=_NOW,
    )
    decision = TradingDecision(
        should_execute=should_execute,
        signal=signal,
        risk_result=None,
        reason=reason,
    )

    return TradingResult(
        executed=False,
        decision=decision,
        order=None,
        reason=reason,
    )


# =============================================================================
# Configuration and Safety Tests
# =============================================================================
def test_paper_runner_evaluates_without_enabling_order_submission() -> None:
    """Verify paper mode can evaluate a cycle but cannot submit an order."""
    asyncio.run(_run_paper_cycle_test())


async def _run_paper_cycle_test() -> None:
    """Execute one paper trading cycle."""
    executor = FakeTradingCycleExecutor(result=_create_result())
    runner = TradingRunner(
        executor=executor,
        symbol=" btcusdt ",
        interval=Interval.M15,
        trade_mode=TradeMode.PAPER,
        candle_limit=50,
    )

    result = await runner.run_once()

    assert result is executor.result
    assert executor.calls == [
        ExecutionCall(
            symbol="BTCUSDT",
            interval=Interval.M15,
            candle_limit=50,
            account_balance_override=Decimal("10000"),
            synchronize_position=False,
            submit_order=False,
        )
    ]
    assert not runner.order_submission_enabled


def test_live_runner_explicitly_enables_order_submission() -> None:
    """Verify only live mode authorizes the workflow to submit orders."""
    asyncio.run(_run_live_cycle_test())


async def _run_live_cycle_test() -> None:
    """Execute one live trading cycle."""
    executor = FakeTradingCycleExecutor(result=_create_result())
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M1,
        trade_mode=TradeMode.LIVE,
    )

    await runner.run_once()

    assert executor.calls[0].account_balance_override is None
    assert executor.calls[0].synchronize_position
    assert executor.calls[0].submit_order
    assert runner.order_submission_enabled


@pytest.mark.parametrize(
    ("symbol", "candle_limit", "cycle_interval_seconds", "message"),
    (
        ("   ", 100, 60.0, "symbol"),
        ("BTCUSDT", 0, 60.0, "candle limit"),
        ("BTCUSDT", 100, 0.0, "cycle interval"),
    ),
)
def test_runner_rejects_invalid_runtime_configuration(
    symbol: str,
    candle_limit: int,
    cycle_interval_seconds: float,
    message: str,
) -> None:
    """Reject invalid runtime values before any trading workflow executes."""
    executor = FakeTradingCycleExecutor(result=_create_result())

    with pytest.raises(ValueError, match=message):
        TradingRunner(
            executor=executor,
            symbol=symbol,
            interval=Interval.M15,
            candle_limit=candle_limit,
            cycle_interval_seconds=cycle_interval_seconds,
        )


def test_runner_rejects_non_positive_paper_balance() -> None:
    """Reject an unusable simulated balance before executing a workflow."""
    executor = FakeTradingCycleExecutor(result=_create_result())

    with pytest.raises(ValueError, match="Paper account balance"):
        TradingRunner(
            executor=executor,
            symbol="BTCUSDT",
            interval=Interval.M15,
            paper_account_balance=Decimal("0"),
        )


# =============================================================================
# Runtime Lifecycle Tests
# =============================================================================
def test_runner_stops_gracefully_without_waiting_for_the_next_interval() -> None:
    """Verify stop interrupts the cycle delay and resets runtime state."""
    asyncio.run(_run_graceful_stop_test())


async def _run_graceful_stop_test() -> None:
    """Start and gracefully stop the continuous runtime."""
    executor = FakeTradingCycleExecutor(result=_create_result())
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        cycle_interval_seconds=60.0,
    )
    task = asyncio.create_task(runner.run())
    await executor.execution_started.wait()

    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert len(executor.calls) == 1
    assert not runner.is_running


def test_runner_waits_while_paused_then_resumes_without_restart() -> None:
    """Verify cooperative pause blocks cycles until the controller resumes."""
    asyncio.run(_run_pause_resume_test())


async def _run_pause_resume_test() -> None:
    """Pause before startup, resume one cycle, and stop normally."""
    executor = FakeTradingCycleExecutor(result=_create_result())
    control = TradingRuntimeControl()
    control.pause()
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        cycle_interval_seconds=60.0,
        runtime_control=control,
    )
    task = asyncio.create_task(runner.run())

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(executor.execution_started.wait(), timeout=0.01)

    assert not executor.calls
    assert control.resume()
    await asyncio.wait_for(executor.execution_started.wait(), timeout=1.0)

    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert len(executor.calls) == 1
    assert not runner.is_running


def test_runner_can_stop_immediately_while_paused() -> None:
    """Verify shutdown does not wait for a paused controller to resume."""
    asyncio.run(_run_stop_while_paused_test())


async def _run_stop_while_paused_test() -> None:
    """Start paused and terminate without executing a trading cycle."""
    executor = FakeTradingCycleExecutor(result=_create_result())
    control = TradingRuntimeControl()
    control.pause()
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        runtime_control=control,
    )
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0)

    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert not executor.calls
    assert not runner.is_running


def test_runner_propagates_cycle_failures_and_resets_state() -> None:
    """Verify workflow errors reach the application failure boundary."""
    asyncio.run(_run_cycle_failure_test())


async def _run_cycle_failure_test() -> None:
    """Execute a failing trading cycle."""
    executor = FakeTradingCycleExecutor(
        result=_create_result(),
        failure=RuntimeError("exchange unavailable"),
    )
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
    )

    with pytest.raises(RuntimeError, match="exchange unavailable"):
        await runner.run()

    assert not runner.is_running


def test_runner_recovers_from_a_transient_cycle_failure() -> None:
    """Retry a bounded transient failure without restarting application resources."""
    asyncio.run(_run_transient_recovery_test())


async def _run_transient_recovery_test() -> None:
    """Fail once, recover on retry, then stop normally."""
    executor = FakeTradingCycleExecutor(
        result=_create_result(),
        failure=RuntimeError("temporary exchange failure"),
        failures_remaining=1,
    )
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        maximum_consecutive_failures=2,
        failure_retry_delay_seconds=0.01,
    )
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(executor.execution_succeeded.wait(), timeout=1.0)

    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert len(executor.calls) == 2
    assert not runner.is_running


def test_runner_propagates_cancellation_and_resets_state() -> None:
    """Verify task cancellation terminates the runtime deterministically."""
    asyncio.run(_run_cancellation_test())


async def _run_cancellation_test() -> None:
    """Cancel a runner while it waits for its next cycle."""
    executor = FakeTradingCycleExecutor(result=_create_result())
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        cycle_interval_seconds=60.0,
    )
    task = asyncio.create_task(runner.run())
    await executor.execution_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert not runner.is_running
