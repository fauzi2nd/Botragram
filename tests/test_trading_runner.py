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
import logging
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
from botragram.app import (
    AutonomousPaperTradingCycleExecutor,
    HumanConfirmedPaperTradingCycleExecutor,
    SingleSymbolTradingCycleExecutor,
    TradingRunner,
    TradingRuntimeControl,
)
from botragram.enums import (
    AuthorizationStatus,
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalType,
    StrategyType,
    TradeMode,
)
from botragram.models import (
    ExecutionAuthorization,
    Order,
    PositionSize,
    RiskMetrics,
    RiskResult,
    Signal,
    TradingDecision,
    TradingResult,
)

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
    ) -> tuple[TradingResult, ...]:
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
        return (self.result,)


@dataclass(slots=True, kw_only=True)
class FakeAutonomousExecutionService:
    """Record autonomous cycle requests without market or order I/O."""

    results: tuple[TradingResult, ...]
    calls: list[tuple[str, Interval, int, int, int, Decimal | None]] = field(
        default_factory=list[tuple[str, Interval, int, int, int, Decimal | None]],
    )

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
        initial_balance: Decimal | None = None,
    ) -> tuple[TradingResult, ...]:
        """Capture one autonomous execution request."""
        self.calls.append(
            (
                quote_asset,
                interval,
                candle_limit,
                max_symbols,
                top_n,
                initial_balance,
            )
        )
        return self.results


@dataclass(slots=True, kw_only=True)
class FakeHumanConfirmationService:
    """Record confirmation discovery requests without executing candidates."""

    authorizations: tuple[ExecutionAuthorization, ...]
    calls: list[tuple[str, Interval, int, int, int]] = field(
        default_factory=list[tuple[str, Interval, int, int, int]],
    )

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> tuple[ExecutionAuthorization, ...]:
        """Capture a confirmation request and return pending authorizations."""
        self.calls.append(
            (quote_asset, interval, candle_limit, max_symbols, top_n),
        )
        return self.authorizations


@dataclass(slots=True, kw_only=True)
class FakeSingleSymbolTradingService:
    """Return a single legacy trading result through the service boundary."""

    result: TradingResult
    calls: list[ExecutionCall] = field(default_factory=list[ExecutionCall])

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
        """Capture one legacy single-symbol execution."""
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
        return self.result


@dataclass(slots=True, kw_only=True)
class BlockingAutonomousExecutionService:
    """Block one autonomous cycle until its owning task is cancelled."""

    execution_started: asyncio.Event = field(default_factory=asyncio.Event)

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
        initial_balance: Decimal | None = None,
    ) -> tuple[TradingResult, ...]:
        """Wait indefinitely so the caller can verify cancellation propagation."""
        del quote_asset, interval, candle_limit, max_symbols, top_n, initial_balance
        self.execution_started.set()
        await asyncio.Event().wait()
        raise RuntimeError("Unreachable after autonomous cancellation")


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


def _create_executed_result() -> TradingResult:
    """Create an executed long entry with complete risk context."""
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.8"),
        strategy_name="test_strategy",
        generated_at=_NOW,
        reason="Fast EMA crossed above slow EMA with positive momentum",
    )
    risk_result = RiskResult(
        approved=True,
        position=PositionSize(
            quantity=Decimal("0.5"),
            notional=Decimal("50"),
            leverage=1,
        ),
        metrics=RiskMetrics(
            entry_price=Decimal("100"),
            stop_loss=Decimal("98"),
            take_profit=Decimal("104"),
            risk_amount=Decimal("1"),
            reward_amount=Decimal("2"),
            risk_reward_ratio=Decimal("2"),
        ),
    )
    decision = TradingDecision(
        should_execute=True,
        signal=signal,
        risk_result=risk_result,
    )
    order = Order(
        order_id="paper-order-1",
        symbol=signal.symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        quantity=risk_result.position.quantity,
        executed_quantity=risk_result.position.quantity,
        price=signal.price,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return TradingResult(
        executed=True,
        decision=decision,
        order=order,
    )


def _complete_startup_configuration(
    control: TradingRuntimeControl,
    *,
    resume: bool = True,
) -> TradingRuntimeControl:
    """Complete the Telegram startup gate for continuous-runner tests."""
    control.confirm_exchange(control.exchange_type)
    control.confirm_market_type(control.market_type)
    control.select_symbol(control.symbol)
    control.select_interval(control.interval)
    control.select_strategy(control.strategy_type)
    control.set_stream_enabled(True)
    control.record_stream_tick(price=Decimal("100"))

    if resume:
        control.resume()

    return control


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

    assert result == (executor.result,)
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


def test_autonomous_paper_executor_receives_only_runtime_inputs() -> None:
    """Verify the runner delegates autonomous cycles without discovery rules."""
    asyncio.run(_run_autonomous_paper_cycle_test())


async def _run_autonomous_paper_cycle_test() -> None:
    """Run one PAPER autonomous cycle through the selected executor."""
    expected = (_create_result(), _create_result())
    service = FakeAutonomousExecutionService(results=expected)
    runner = TradingRunner(
        executor=AutonomousPaperTradingCycleExecutor(
            autonomous_execution_service=service,
            quote_asset="usdt",
            max_symbols=7,
            top_n=3,
        ),
        symbol="BTCUSDT",
        interval=Interval.M5,
        trade_mode=TradeMode.PAPER,
        candle_limit=120,
        paper_account_balance=Decimal("2500"),
        runtime_control=TradingRuntimeControl(interval=Interval.M5),
    )

    results = await runner.run_once()

    assert results == expected
    assert service.calls == [
        ("USDT", Interval.M5, 120, 7, 3, Decimal("2500")),
    ]


def test_autonomous_executor_rejects_order_enabled_invocation() -> None:
    """Verify autonomous runtime execution cannot enable order submission."""
    asyncio.run(_run_autonomous_live_guard_test())


def test_human_confirmation_executor_prepares_without_order_submission() -> None:
    """Keep the runtime adapter separate from confirmation business logic."""
    asyncio.run(_run_human_confirmation_cycle_test())


async def _run_human_confirmation_cycle_test() -> None:
    """Run one non-executing human-confirmation cycle through the runner."""
    signal = _create_result(should_execute=True).decision.signal
    authorization = ExecutionAuthorization(
        authorization_id="12345678123456781234567812345678",
        signal=signal,
        status=AuthorizationStatus.PENDING,
        created_at=_NOW,
        expires_at=_NOW.replace(minute=5),
    )
    service = FakeHumanConfirmationService(authorizations=(authorization,))
    runner = TradingRunner(
        executor=HumanConfirmedPaperTradingCycleExecutor(
            human_confirmation_service=service,
            quote_asset="usdt",
            max_symbols=7,
            top_n=3,
        ),
        symbol="BTCUSDT",
        interval=Interval.M15,
        trade_mode=TradeMode.PAPER,
    )

    results = await runner.run_once()

    assert service.calls == [("USDT", Interval.M15, 100, 7, 3)]
    assert len(results) == 1
    assert not results[0].executed
    assert results[0].reason == "Pending human PAPER approval"


async def _run_autonomous_live_guard_test() -> None:
    """Attempt an order-enabled autonomous cycle."""
    service = FakeAutonomousExecutionService(results=())
    executor = AutonomousPaperTradingCycleExecutor(
        autonomous_execution_service=service,
        quote_asset="USDT",
        max_symbols=7,
        top_n=3,
    )

    with pytest.raises(RuntimeError, match="restricted to paper mode"):
        await executor.execute(
            symbol="BTCUSDT",
            interval=Interval.M15,
            candle_limit=100,
            submit_order=True,
        )

    assert service.calls == []


def test_autonomous_runner_propagates_cancellation() -> None:
    """Verify cancelling a runtime cycle cancels its autonomous execution."""
    asyncio.run(_run_autonomous_cancellation_test())


async def _run_autonomous_cancellation_test() -> None:
    """Cancel an in-flight autonomous cycle."""
    service = BlockingAutonomousExecutionService()
    runner = TradingRunner(
        executor=AutonomousPaperTradingCycleExecutor(
            autonomous_execution_service=service,
            quote_asset="USDT",
            max_symbols=7,
            top_n=3,
        ),
        symbol="BTCUSDT",
        interval=Interval.M15,
    )
    task = asyncio.create_task(runner.run_once())
    await service.execution_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert not runner.runtime_control.cycle_in_progress


def test_single_symbol_executor_preserves_existing_workflow() -> None:
    """Verify the disabled autonomous path delegates to TradingService unchanged."""
    asyncio.run(_run_single_symbol_executor_test())


async def _run_single_symbol_executor_test() -> None:
    """Execute the adapter over the original single-symbol fake."""
    service = FakeSingleSymbolTradingService(result=_create_result())
    executor = SingleSymbolTradingCycleExecutor(trading_service=service)

    results = await executor.execute(
        symbol="BTCUSDT",
        interval=Interval.M15,
        candle_limit=100,
        account_balance_override=Decimal("10000"),
        synchronize_position=False,
        submit_order=False,
    )

    assert results == (service.result,)
    assert service.calls[0].submit_order is False


def test_runner_logs_executed_position_reason_and_risk(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Expose successful position direction, reason, SL, TP, and risk."""
    runner = TradingRunner(
        executor=FakeTradingCycleExecutor(result=_create_executed_result()),
        symbol="BTCUSDT",
        interval=Interval.M1,
    )

    with caplog.at_level(logging.INFO, logger="botragram.app.trading_runner"):
        asyncio.run(runner.run_once())

    assert "position=LONG" in caplog.text
    assert "reason=Fast EMA crossed above slow EMA" in caplog.text
    assert "risk_amount=1" in caplog.text
    assert "stop_loss=98" in caplog.text
    assert "take_profit=104" in caplog.text


def test_runtime_selection_requires_pause_and_changes_future_cycles() -> None:
    """Verify Telegram-style selection safely changes the next runner cycle."""
    asyncio.run(_run_runtime_selection_test())


def test_default_cycle_cadence_follows_telegram_interval_selection() -> None:
    """Use the latest runtime interval rather than the startup interval."""
    control = TradingRuntimeControl(interval=Interval.M15)
    runner = TradingRunner(
        executor=FakeTradingCycleExecutor(result=_create_result()),
        symbol="BTCUSDT",
        interval=Interval.M15,
        runtime_control=control,
    )

    assert runner.effective_cycle_interval_seconds == 900.0

    control.select_interval(Interval.M1)

    assert runner.effective_cycle_interval_seconds == 60.0


async def _run_runtime_selection_test() -> None:
    """Pause, select a market and strategy, then execute the new selection."""
    executor = FakeTradingCycleExecutor(result=_create_result())
    control = TradingRuntimeControl()
    selected_strategies: list[StrategyType] = []
    control.bind_strategy_selector(selected_strategies.append)
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        runtime_control=control,
    )

    control.pause()
    assert control.select_symbol("ethusdt")
    assert control.select_interval(Interval.M5)
    assert control.select_strategy(StrategyType.SUPERTREND)
    control.confirm_exchange(control.exchange_type)
    control.confirm_market_type(control.market_type)
    control.set_stream_enabled(True)
    control.record_stream_tick(price=Decimal("100"))
    control.resume()
    await runner.run_once()

    assert executor.calls[0].symbol == "ETHUSDT"
    assert executor.calls[0].interval is Interval.M5
    assert selected_strategies == [StrategyType.SUPERTREND]


def test_runtime_selection_is_rejected_while_trading_is_active() -> None:
    """Verify an active cycle configuration cannot be changed concurrently."""
    control = _complete_startup_configuration(TradingRuntimeControl())

    with pytest.raises(RuntimeError, match="Pause trading"):
        control.select_symbol("ETHUSDT")


def test_runtime_start_requires_complete_telegram_configuration() -> None:
    """Reject startup until selections, subscription, and first tick are ready."""
    control = TradingRuntimeControl()

    assert control.is_paused
    assert control.get_missing_startup_requirements() == (
        "exchange",
        "market type",
        "symbol",
        "interval",
        "strategy",
        "stream subscription",
    )

    with pytest.raises(RuntimeError, match="Startup configuration incomplete"):
        control.resume()

    _complete_startup_configuration(control)

    assert not control.is_paused
    assert not control.get_missing_startup_requirements()


def test_runtime_selection_waits_for_current_cycle_after_pause() -> None:
    """Verify pausing does not mutate settings owned by an executing cycle."""
    control = TradingRuntimeControl()
    control.begin_cycle()
    control.pause()

    with pytest.raises(RuntimeError, match="cycle to finish"):
        control.select_symbol("ETHUSDT")

    control.end_cycle()


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
        runtime_control=_complete_startup_configuration(TradingRuntimeControl()),
    )
    task = asyncio.create_task(runner.run())
    await executor.execution_started.wait()

    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert len(executor.calls) == 1
    assert not runner.is_running


def test_runner_logs_periodic_heartbeat(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify a healthy waiting runtime remains visibly alive in the terminal."""
    asyncio.run(_run_heartbeat_test(caplog=caplog))


async def _run_heartbeat_test(
    *,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Run long enough to emit one heartbeat before graceful shutdown."""
    executor = FakeTradingCycleExecutor(result=_create_result())
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        cycle_interval_seconds=60,
        heartbeat_interval_seconds=0.01,
        runtime_control=_complete_startup_configuration(TradingRuntimeControl()),
    )

    with caplog.at_level(logging.INFO, logger="botragram.app.trading_runner"):
        task = asyncio.create_task(runner.run())
        await executor.execution_started.wait()
        await asyncio.sleep(0.03)
        runner.stop()
        await asyncio.wait_for(task, timeout=1.0)

    assert "Runtime heartbeat" in caplog.text


def test_runner_waits_while_paused_then_resumes_without_restart() -> None:
    """Verify cooperative pause blocks cycles until the controller resumes."""
    asyncio.run(_run_pause_resume_test())


async def _run_pause_resume_test() -> None:
    """Pause before startup, resume one cycle, and stop normally."""
    executor = FakeTradingCycleExecutor(result=_create_result())
    control = _complete_startup_configuration(
        TradingRuntimeControl(),
        resume=False,
    )
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
        runtime_control=_complete_startup_configuration(TradingRuntimeControl()),
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
        runtime_control=_complete_startup_configuration(TradingRuntimeControl()),
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
        runtime_control=_complete_startup_configuration(TradingRuntimeControl()),
    )
    task = asyncio.create_task(runner.run())
    await executor.execution_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert not runner.is_running
