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
from collections.abc import Callable
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
    MultiContextRunnerActivationPreconditions,
    SingleSymbolTradingCycleExecutor,
    TradingRunner,
    TradingRuntimeControl,
    calculate_seconds_until_next_candle_close,
)
from botragram.app.global_discovery_telemetry import GlobalDiscoveryTelemetry
from botragram.app.trading_runner import GlobalDiscoveryCycleReport
from botragram.enums import (
    AuthorizationStatus,
    GlobalDiscoveryCycleOutcome,
    Interval,
    LiveMarketStreamLifecycleStatus,
    LivePortfolioRecoveryStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalType,
    StrategyType,
    TradeMode,
)
from botragram.models import (
    ExecutionAuthorization,
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveProtectionMonitorState,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePositionContext,
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
    strategy_type: StrategyType | None
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
        """Capture one complete executor invocation."""
        del live_management_authorization, current_drawdown_pct, order_type, price
        self.calls.append(
            ExecutionCall(
                symbol=symbol,
                interval=interval,
                strategy_type=strategy_type,
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


class FailingCompletionTelemetry(GlobalDiscoveryTelemetry):
    """Raise after a successful global executor result is available."""

    def complete_cycle(
        self, *, results: tuple[TradingResult, ...], **_: object
    ) -> None:
        """Simulate a presentation-only completion failure."""
        del results
        self.completion_calls += 1
        raise RuntimeError("telemetry completion failed")

    completion_calls: int = 0


@dataclass(slots=True, kw_only=True)
class SuccessfulGlobalExecutor:
    """Exercise the runner's real global-executor branch."""

    results: tuple[TradingResult, ...]
    calls: int = 0
    active_cycles: int = 0
    maximum_active_cycles: int = 0
    stop_after_calls: int | None = None
    stop_callback: Callable[[], None] | None = None

    async def execute_global(
        self,
        *,
        interval: Interval,
        candle_limit: int,
    ) -> tuple[TradingResult, ...]:
        """Return one known successful global-cycle result."""
        del interval, candle_limit
        self.active_cycles += 1
        self.maximum_active_cycles = max(
            self.maximum_active_cycles,
            self.active_cycles,
        )
        try:
            await asyncio.sleep(0)
            return self.results
        finally:
            self.active_cycles -= 1
            self.calls += 1
            if (
                self.stop_after_calls is not None
                and self.calls >= self.stop_after_calls
                and self.stop_callback is not None
            ):
                self.stop_callback()

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
        """Satisfy the general runner protocol without using this path."""
        _ = (
            symbol,
            interval,
            candle_limit,
            strategy_type,
            live_management_authorization,
            current_drawdown_pct,
            order_type,
            price,
            account_balance_override,
            synchronize_position,
            submit_order,
        )
        raise AssertionError("Global runner selected the single-context executor path")


@dataclass(slots=True, kw_only=True)
class ReportingGlobalExecutor:
    """Return typed discovery facts while preserving the legacy global method."""

    report: GlobalDiscoveryCycleReport
    report_calls: int = 0
    legacy_calls: int = 0

    async def execute_global_report(
        self,
        *,
        interval: Interval,
        candle_limit: int,
    ) -> GlobalDiscoveryCycleReport:
        """Return one immutable report for the runner telemetry path."""
        del interval, candle_limit
        self.report_calls += 1
        return self.report

    async def execute_global(
        self,
        *,
        interval: Interval,
        candle_limit: int,
    ) -> tuple[TradingResult, ...]:
        """Remain structurally compatible without being selected by the runner."""
        del interval, candle_limit
        self.legacy_calls += 1
        return self.report.results

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
        """Satisfy the general runner protocol without using this path."""
        _ = (
            symbol,
            interval,
            candle_limit,
            strategy_type,
            live_management_authorization,
            current_drawdown_pct,
            order_type,
            price,
            account_balance_override,
            synchronize_position,
            submit_order,
        )
        raise AssertionError("Reporting global executor used the single-context path")


@dataclass(slots=True, kw_only=True)
class FailingGlobalExecutor:
    """Raise from the global cycle after telemetry has entered SCANNING."""

    error: Exception

    async def execute_global(
        self,
        *,
        interval: Interval,
        candle_limit: int,
    ) -> tuple[TradingResult, ...]:
        """Raise the configured global-cycle error."""
        del interval, candle_limit
        raise self.error

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
        """Satisfy the general runner protocol without using this path."""
        _ = (
            symbol,
            interval,
            candle_limit,
            strategy_type,
            live_management_authorization,
            current_drawdown_pct,
            order_type,
            price,
            account_balance_override,
            synchronize_position,
            submit_order,
        )
        raise AssertionError("Failing global executor used the single-context path")


@dataclass(slots=True, kw_only=True)
class SequentialContextExecutor:
    """Measure cycle ordering without parallel task execution."""

    result: TradingResult
    events: list[str] = field(default_factory=list[str])
    strategy_types: list[StrategyType | None] = field(
        default_factory=list[StrategyType | None],
    )
    active_cycles: int = 0
    maximum_active_cycles: int = 0
    cancel_symbol: str | None = None
    failure_symbol: str | None = None
    on_cycle_started: Callable[[str], None] | None = None

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
        """Record one context cycle and expose sequential execution state."""
        _ = (
            interval,
            candle_limit,
            live_management_authorization,
            current_drawdown_pct,
            order_type,
            price,
            account_balance_override,
            synchronize_position,
            submit_order,
        )
        self.events.append(f"start:{symbol}")
        if self.on_cycle_started is not None:
            self.on_cycle_started(symbol)
        self.strategy_types.append(strategy_type)
        self.active_cycles += 1
        self.maximum_active_cycles = max(self.maximum_active_cycles, self.active_cycles)

        try:
            if symbol == self.cancel_symbol:
                raise asyncio.CancelledError()
            if symbol == self.failure_symbol:
                raise RuntimeError(f"configured context failure: {symbol}")
            await asyncio.sleep(0)
            self.events.append(f"complete:{symbol}")
            return (self.result,)
        finally:
            self.active_cycles -= 1


@dataclass(slots=True, kw_only=True)
class _MultiContextActivationProvider:
    """Build exact ready activation state from one runtime-control snapshot."""

    control: TradingRuntimeControl
    contexts: tuple[LiveRuntimePositionContext, ...]
    stream_states: tuple[LiveMarketStreamState, ...]
    monitor_states: tuple[LiveProtectionMonitorState, ...]

    def get_multi_context_activation_preconditions(
        self,
        *,
        runtime_is_stopping: bool,
    ) -> MultiContextRunnerActivationPreconditions | None:
        """Return exact current activation state for the runner protocol."""
        authorization = self.control.live_management_authorization
        if authorization is None:
            return None

        return MultiContextRunnerActivationPreconditions(
            portfolio_status=LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE,
            contexts=self.contexts,
            stream_states=self.stream_states,
            monitor_states=self.monitor_states,
            live_management_authorization=authorization,
            runtime_is_paused=self.control.is_paused,
            runtime_is_stopping=runtime_is_stopping,
        )


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
    ) -> TradingResult:
        """Capture one legacy single-symbol execution."""
        del live_management_authorization, current_drawdown_pct, order_type, price
        self.calls.append(
            ExecutionCall(
                symbol=symbol,
                interval=interval,
                strategy_type=strategy_type,
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


def _context(
    *,
    symbol: str,
    interval: Interval,
    strategy_type: StrategyType = StrategyType.EMA_CROSS,
) -> LiveRuntimePositionContext:
    """Build one immutable runtime context for scheduler-foundation tests."""
    return LiveRuntimePositionContext(
        symbol=symbol,
        interval=interval,
        strategy_type=strategy_type,
    )


def _ready_stream_state(
    *,
    context: LiveRuntimePositionContext,
) -> LiveMarketStreamState:
    """Build an exact ready stream state for activation-policy tests."""
    return LiveMarketStreamState(
        identity=LiveMarketStreamIdentity.from_runtime_context(context=context),
        lifecycle_status=LiveMarketStreamLifecycleStatus.RUNNING,
        first_tick_received=True,
        event_count=1,
        last_price=Decimal("100"),
        last_event_monotonic=1.0,
    )


def _healthy_monitor_state(
    *,
    context: LiveRuntimePositionContext,
) -> LiveProtectionMonitorState:
    """Build an exact healthy monitor state for activation-policy tests."""
    return LiveProtectionMonitorState(
        context=context,
        is_active=True,
    )


# =============================================================================
# Configuration and Safety Tests
# =============================================================================
def test_context_cycle_receives_the_exact_explicit_context() -> None:
    """Verify the new cycle boundary forwards BTC context without control lookup."""
    asyncio.run(_run_explicit_context_cycle_test())


async def _run_explicit_context_cycle_test() -> None:
    """Execute one BTC context through the context-explicit boundary."""
    executor = FakeTradingCycleExecutor(result=_create_result())
    control = TradingRuntimeControl()
    runner = TradingRunner(
        executor=executor,
        symbol="SOLUSDT",
        interval=Interval.H1,
        runtime_control=control,
    )

    await runner.run_context_cycle(
        context=_context(symbol="BTCUSDT", interval=Interval.M1),
    )

    assert executor.calls[0].symbol == "BTCUSDT"
    assert executor.calls[0].interval is Interval.M1
    assert executor.calls[0].strategy_type is StrategyType.EMA_CROSS
    assert control.symbol == "SOLUSDT"


def test_context_scheduler_is_deterministic_and_sequential() -> None:
    """Verify BTC fully completes before ETH begins without task fan-out."""
    asyncio.run(_run_sequential_context_scheduler_test())


async def _run_sequential_context_scheduler_test() -> None:
    """Run BTC then ETH through the isolated sequential scheduler foundation."""
    executor = SequentialContextExecutor(result=_create_result())
    control = TradingRuntimeControl()
    control.set_runtime_contexts(
        contexts=(
            _context(symbol="BTCUSDT", interval=Interval.M1),
            _context(
                symbol="ETHUSDT",
                interval=Interval.H1,
                strategy_type=StrategyType.EMA_SCALPING,
            ),
        ),
    )
    runner = TradingRunner(
        executor=executor,
        symbol="SOLUSDT",
        interval=Interval.M15,
        runtime_control=control,
    )

    results = await runner.run_context_cycles_once(
        contexts=control.runtime_contexts,
    )

    assert len(results) == 2
    assert executor.events == [
        "start:BTCUSDT",
        "complete:BTCUSDT",
        "start:ETHUSDT",
        "complete:ETHUSDT",
    ]
    assert executor.maximum_active_cycles == 1
    assert executor.strategy_types == [
        StrategyType.EMA_CROSS,
        StrategyType.EMA_SCALPING,
    ]
    assert not control.cycle_in_progress


def test_context_scheduler_propagates_cancellation_before_next_context() -> None:
    """Verify cancellation of BTC cannot be isolated by starting ETH."""
    asyncio.run(_run_context_scheduler_cancellation_test())


async def _run_context_scheduler_cancellation_test() -> None:
    """Cancel the first explicit context before a second context can start."""
    executor = SequentialContextExecutor(
        result=_create_result(),
        cancel_symbol="BTCUSDT",
    )
    runner = TradingRunner(
        executor=executor,
        symbol="SOLUSDT",
        interval=Interval.M15,
    )

    with pytest.raises(asyncio.CancelledError):
        await runner.run_context_cycles_once(
            contexts=(
                _context(symbol="BTCUSDT", interval=Interval.M1),
                _context(symbol="ETHUSDT", interval=Interval.H1),
            ),
        )

    assert executor.events == ["start:BTCUSDT"]
    assert executor.maximum_active_cycles == 1


def test_context_scheduler_propagates_failure_before_next_context() -> None:
    """Verify a failed BTC context cannot silently proceed to ETH."""
    asyncio.run(_run_context_scheduler_failure_test())


async def _run_context_scheduler_failure_test() -> None:
    """Fail the first explicit context and prove no later cycle begins."""
    executor = SequentialContextExecutor(
        result=_create_result(),
        failure_symbol="BTCUSDT",
    )
    runner = TradingRunner(
        executor=executor,
        symbol="SOLUSDT",
        interval=Interval.M15,
    )

    with pytest.raises(RuntimeError, match="configured context failure"):
        await runner.run_context_cycles_once(
            contexts=(
                _context(symbol="BTCUSDT", interval=Interval.M1),
                _context(symbol="ETHUSDT", interval=Interval.H1),
            ),
        )

    assert executor.events == ["start:BTCUSDT"]


def test_runner_lifecycle_uses_multiple_contexts_sequentially() -> None:
    """Support one global runner lifecycle without per-context runner tasks."""
    asyncio.run(_run_multi_context_lifecycle_test())


async def _run_multi_context_lifecycle_test() -> None:
    """Run a stable batch despite a runtime-context change during BTC."""
    control = TradingRuntimeControl()
    _complete_startup_configuration(control)
    control.set_runtime_contexts(
        contexts=(
            _context(symbol="BTCUSDT", interval=Interval.M1),
            _context(symbol="ETHUSDT", interval=Interval.H1),
        ),
    )

    def change_contexts_after_btc(symbol: str) -> None:
        """Install a new portfolio only after the immutable batch begins."""
        if symbol != "BTCUSDT":
            return

        control.set_runtime_contexts(
            contexts=(
                _context(symbol="BTCUSDT", interval=Interval.M1),
                _context(symbol="SOLUSDT", interval=Interval.M15),
            ),
        )

    executor = SequentialContextExecutor(
        result=_create_result(),
        on_cycle_started=change_contexts_after_btc,
    )
    runner = TradingRunner(
        executor=executor,
        symbol="SOLUSDT",
        interval=Interval.M15,
        runtime_control=control,
    )

    task = asyncio.create_task(runner.run())
    for _ in range(100):
        if executor.events == [
            "start:BTCUSDT",
            "complete:BTCUSDT",
            "start:ETHUSDT",
            "complete:ETHUSDT",
        ]:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("Multi-context batch did not complete")

    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert executor.maximum_active_cycles == 1
    assert not runner.is_running


def test_multi_context_activation_preconditions_require_exact_ready_owners() -> None:
    """Require exact streams and monitors without using protection-ready state."""
    contexts = (
        _context(symbol="BTCUSDT", interval=Interval.M1),
        _context(symbol="ETHUSDT", interval=Interval.M5),
    )
    ready = MultiContextRunnerActivationPreconditions(
        portfolio_status=LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE,
        contexts=contexts,
        stream_states=tuple(
            _ready_stream_state(context=context) for context in contexts
        ),
        monitor_states=tuple(
            _healthy_monitor_state(context=context) for context in contexts
        ),
        live_management_authorization=LiveRecoveredPositionManagementAuthorization(
            contexts=contexts,
            runtime_management_allowed=True,
        ),
        runtime_is_paused=False,
        runtime_is_stopping=False,
    )

    assert ready.runtime_representation_valid
    assert ready.stream_substrate_ready
    assert ready.protection_monitoring_ready
    assert ready.is_eligible

    missing_stream = MultiContextRunnerActivationPreconditions(
        portfolio_status=ready.portfolio_status,
        contexts=contexts,
        stream_states=ready.stream_states[:1],
        monitor_states=ready.monitor_states,
        live_management_authorization=ready.live_management_authorization,
        runtime_is_paused=False,
        runtime_is_stopping=False,
    )
    failed_monitor = MultiContextRunnerActivationPreconditions(
        portfolio_status=ready.portfolio_status,
        contexts=contexts,
        stream_states=ready.stream_states,
        monitor_states=(
            ready.monitor_states[0],
            LiveProtectionMonitorState(
                context=contexts[1],
                is_active=True,
                failure_type="RuntimeError",
            ),
        ),
        live_management_authorization=ready.live_management_authorization,
        runtime_is_paused=False,
        runtime_is_stopping=False,
    )

    assert not missing_stream.is_eligible
    assert not failed_monitor.protection_monitoring_ready
    assert not failed_monitor.is_eligible

    unauthorized = MultiContextRunnerActivationPreconditions(
        portfolio_status=ready.portfolio_status,
        contexts=contexts,
        stream_states=ready.stream_states,
        monitor_states=ready.monitor_states,
        live_management_authorization=LiveRecoveredPositionManagementAuthorization(
            contexts=contexts,
        ),
        runtime_is_paused=False,
        runtime_is_stopping=False,
    )

    assert not unauthorized.is_eligible


def test_live_multi_context_runner_requires_exact_ready_management_authorization() -> (
    None
):
    """Run exactly one global LIVE batch only after exact activation succeeds."""
    asyncio.run(_run_live_multi_context_management_test())


async def _run_live_multi_context_management_test() -> None:
    """Activate BTC and ETH management sequentially without any new entry path."""
    contexts = (
        _context(symbol="BTCUSDT", interval=Interval.M1),
        _context(symbol="ETHUSDT", interval=Interval.M5),
    )
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=contexts)
    control.set_live_management_authorization(
        authorization=LiveRecoveredPositionManagementAuthorization(
            contexts=contexts,
            runtime_management_allowed=True,
        ),
    )
    control.set_position_protection_ready(True)
    control.resume()
    executor = SequentialContextExecutor(result=_create_result())
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        trade_mode=TradeMode.LIVE,
        runtime_control=control,
        multi_context_activation_precondition_provider=(
            _MultiContextActivationProvider(
                control=control,
                contexts=contexts,
                stream_states=tuple(
                    _ready_stream_state(context=context) for context in contexts
                ),
                monitor_states=tuple(
                    _healthy_monitor_state(context=context) for context in contexts
                ),
            )
        ),
    )

    task = asyncio.create_task(runner.run())
    for _ in range(100):
        if executor.events == [
            "start:BTCUSDT",
            "complete:BTCUSDT",
            "start:ETHUSDT",
            "complete:ETHUSDT",
        ]:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("Authorized multi-context LIVE batch did not complete")

    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert executor.maximum_active_cycles == 1


@pytest.mark.parametrize(
    "failed_owner",
    ("stream", "monitor"),
)
def test_live_multi_context_runner_pauses_before_a_batch_when_owner_is_unhealthy(
    failed_owner: str,
) -> None:
    """Block the complete portfolio when a required owner becomes unhealthy."""
    asyncio.run(_run_live_multi_context_unhealthy_owner_test(failed_owner=failed_owner))


async def _run_live_multi_context_unhealthy_owner_test(
    *,
    failed_owner: str,
) -> None:
    """Verify owner health is revalidated before every LIVE context batch."""
    contexts = (
        _context(symbol="BTCUSDT", interval=Interval.M1),
        _context(symbol="ETHUSDT", interval=Interval.M5),
    )
    control = TradingRuntimeControl()
    control.set_runtime_contexts(contexts=contexts)
    control.set_live_management_authorization(
        authorization=LiveRecoveredPositionManagementAuthorization(
            contexts=contexts,
            runtime_management_allowed=True,
        ),
    )
    control.set_position_protection_ready(True)
    control.resume()
    stream_states = tuple(_ready_stream_state(context=context) for context in contexts)
    monitor_states = tuple(
        _healthy_monitor_state(context=context) for context in contexts
    )

    if failed_owner == "stream":
        stream_states = (
            stream_states[0],
            LiveMarketStreamState(
                identity=stream_states[1].identity,
                lifecycle_status=LiveMarketStreamLifecycleStatus.FAILED,
                first_tick_received=True,
                event_count=1,
                last_price=Decimal("100"),
                last_event_monotonic=1.0,
            ),
        )
    else:
        monitor_states = (
            monitor_states[0],
            LiveProtectionMonitorState(
                context=contexts[1],
                is_active=True,
                failure_type="RuntimeError",
            ),
        )

    executor = SequentialContextExecutor(result=_create_result())
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        trade_mode=TradeMode.LIVE,
        runtime_control=control,
        multi_context_activation_precondition_provider=(
            _MultiContextActivationProvider(
                control=control,
                contexts=contexts,
                stream_states=stream_states,
                monitor_states=monitor_states,
            )
        ),
    )

    task = asyncio.create_task(runner.run())
    for _ in range(100):
        if control.is_paused:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("Unhealthy owner did not pause the LIVE runtime")

    runner.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert executor.events == []
    assert control.live_management_authorization is None


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
            strategy_type=StrategyType.EMA_CROSS,
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


def test_global_telemetry_failure_does_not_fail_successful_cycle() -> None:
    """Keep telemetry completion failures outside the trading success boundary."""
    expected = (_create_result(),)
    executor = SuccessfulGlobalExecutor(results=expected)
    telemetry = FailingCompletionTelemetry(interval=Interval.M1)
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M1,
        global_discovery_telemetry=telemetry,
    )

    assert asyncio.run(runner.run_once()) == expected
    assert executor.calls == 1
    assert telemetry.completion_calls == 1


def test_global_runner_preserves_capacity_skip_outcome_while_waiting() -> None:
    """Keep capacity skip as the last outcome after phase returns to WAITING."""
    telemetry = GlobalDiscoveryTelemetry(
        interval=Interval.M1,
        universe_limit=100,
        batch_size=20,
        top_n=5,
    )
    executor = ReportingGlobalExecutor(
        report=GlobalDiscoveryCycleReport(skipped_capacity=True)
    )
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M1,
        global_discovery_telemetry=telemetry,
    )

    assert asyncio.run(runner.run_once()) == ()
    snapshot = telemetry.get_snapshot()
    assert snapshot.last_outcome is GlobalDiscoveryCycleOutcome.SKIPPED_CAPACITY
    assert snapshot.scanned_count == 0
    assert snapshot.actionable_count == 0
    assert snapshot.candidates == ()
    assert executor.report_calls == 1
    assert executor.legacy_calls == 0

    telemetry.wait_until(next_eligible_monotonic=123.0)
    waiting = telemetry.get_snapshot()
    assert waiting.state.value == "waiting"
    assert waiting.last_outcome is GlobalDiscoveryCycleOutcome.SKIPPED_CAPACITY


def test_global_runner_reports_rate_limit_skip_without_failure() -> None:
    """Expose deliberate discovery throttling as a normal empty cycle."""
    telemetry = GlobalDiscoveryTelemetry(interval=Interval.M1)
    executor = ReportingGlobalExecutor(
        report=GlobalDiscoveryCycleReport(skipped_rate_limit=True)
    )
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M1,
        global_discovery_telemetry=telemetry,
    )

    assert asyncio.run(runner.run_once()) == ()
    snapshot = telemetry.get_snapshot()
    assert snapshot.last_outcome is GlobalDiscoveryCycleOutcome.SKIPPED_RATE_LIMIT
    assert snapshot.scanned_count == 0
    assert snapshot.actionable_count == 0
    assert snapshot.candidates == ()
    assert executor.report_calls == 1
    assert executor.legacy_calls == 0


def test_global_runner_records_failed_cycle_outcome() -> None:
    """Expose global-cycle failure as telemetry without swallowing the exception."""
    telemetry = GlobalDiscoveryTelemetry(interval=Interval.M1)
    runner = TradingRunner(
        executor=FailingGlobalExecutor(error=RuntimeError("boom")),
        symbol="BTCUSDT",
        interval=Interval.M1,
        global_discovery_telemetry=telemetry,
    )

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(runner.run_once())

    snapshot = telemetry.get_snapshot()
    assert snapshot.last_outcome is GlobalDiscoveryCycleOutcome.FAILED
    assert snapshot.cycle_in_progress is False
    assert snapshot.scanned_count is None


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


def test_autonomous_global_cadence_uses_optional_override_or_interval_default() -> None:
    """Preserve interval cadence when absent and accept the explicit override."""
    executor = SuccessfulGlobalExecutor(results=())

    default_runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M1,
    )
    override_runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M1,
        cycle_interval_seconds=10,
    )

    assert default_runner.effective_cycle_interval_seconds == 60.0
    assert override_runner.effective_cycle_interval_seconds == 10.0


def test_autonomous_global_cadence_never_overlaps_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the sole global loop serialized even when cadence is immediately due."""
    asyncio.run(_run_non_overlapping_global_cadence_test(monkeypatch=monkeypatch))


async def _run_non_overlapping_global_cadence_test(
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_value = 0.0

    def advancing_monotonic() -> float:
        """Move beyond each scheduled deadline without a wall-clock sleep."""
        nonlocal monotonic_value
        monotonic_value += 100.0
        return monotonic_value

    monkeypatch.setattr(
        "botragram.app.trading_runner.monotonic",
        advancing_monotonic,
    )
    control = TradingRuntimeControl()
    control.resume_global_cycle()
    executor = SuccessfulGlobalExecutor(results=(), stop_after_calls=2)
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M1,
        cycle_interval_seconds=10,
        runtime_control=control,
    )
    executor.stop_callback = runner.stop

    await runner.run()

    assert executor.calls == 2
    assert executor.maximum_active_cycles == 1
    assert not runner.is_running


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


def test_runner_calculate_seconds_until_next_candle_close_5m() -> None:
    """Verify 5m candle close delay calculation with default 2.0s buffer."""
    # Base divisible by 300: 300 * 1000 = 300_000.0
    base = 300_000.0
    # 70 seconds into a 300s candle: remaining = 230s + 2s buffer = 232s
    delay = calculate_seconds_until_next_candle_close(
        interval=Interval.M5, wall_time=base + 70.0
    )
    assert delay == pytest.approx(232.0)

    # 1 second before candle close: remaining = 1s + 2s buffer = 3s
    delay = calculate_seconds_until_next_candle_close(
        interval=Interval.M5, wall_time=base + 299.0
    )
    assert delay == pytest.approx(3.0)

    # 1 second after candle close: remaining = (300 - 1) + 2 = 301s
    delay = calculate_seconds_until_next_candle_close(
        interval=Interval.M5, wall_time=base + 301.0
    )
    assert delay == pytest.approx(301.0)


def test_runner_calculate_seconds_until_next_candle_close_15m_and_1h() -> None:
    """Verify 15m and 1h candle close delay calculations."""
    # Base divisible by 900: 900_000.0
    base_15m = 900_000.0
    # 100 seconds into a 900s candle (15m): remaining = 800s + 2s buffer = 802s
    delay = calculate_seconds_until_next_candle_close(
        interval=Interval.M15, wall_time=base_15m + 100.0
    )
    assert delay == pytest.approx(802.0)

    # For 1h interval (3600s): base 3_600_000.0, 600s into candle:
    # remaining = 3000s + 2s = 3002s
    base_1h = 3_600_000.0
    delay = calculate_seconds_until_next_candle_close(
        interval=Interval.H1, wall_time=base_1h + 600.0
    )
    assert delay == pytest.approx(3002.0)


def test_runner_global_cadence_auto_syncs_and_respects_override() -> None:
    """Ensure cadence auto-syncs when None and returns explicit override when set."""
    executor = SuccessfulGlobalExecutor(results=())
    runner_auto = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M5,
        cycle_interval_seconds=None,
    )
    assert runner_auto.effective_cycle_interval_seconds == 300.0
    delay = runner_auto.calculate_seconds_until_next_candle_close()
    assert 0.0 < delay <= 302.0

    runner_explicit = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M5,
        cycle_interval_seconds=45.0,
    )
    assert runner_explicit.effective_cycle_interval_seconds == 45.0
