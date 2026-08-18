"""TESTNET autonomous LIVE discovery-cycle orchestration tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from botragram.app import (
    AutonomousLiveCycleUnsafeError,
    AutonomousLiveTradingCycleExecutor,
    TradingRunner,
    TradingRuntimeControl,
)
from botragram.config.risk_settings import RiskSettings
from botragram.engine import RiskEngine
from botragram.enums import (
    AutonomousLiveEntryExecutionStatus,
    ExchangeEnvironment,
    ExecutionPolicy,
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalType,
    StrategyType,
    TradeMode,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    AutonomousLiveEntryExecutionResult,
    AutonomousLiveEntryIntent,
    LiveEntryRiskEvaluation,
    Order,
    Signal,
    TradingDecision,
)
from botragram.services import AutonomousLiveEntryIntentService

_NOW = datetime(2026, 8, 18, tzinfo=timezone.utc)


def _signal(*, symbol: str) -> Signal:
    """Create one ranked actionable signal."""
    return Signal(
        symbol=symbol,
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.9"),
        strategy_name=StrategyType.EMA_CROSS.value,
        generated_at=_NOW,
    )


def _decision(*, signal: Signal, approved: bool = True) -> TradingDecision:
    """Create one deterministic canonical-risk decision."""
    risk_result = RiskEngine(settings=RiskSettings()).evaluate(
        signal=signal,
        account_balance=Decimal("1000"),
    )
    return TradingDecision(
        should_execute=approved,
        signal=signal,
        risk_result=risk_result if approved else None,
        reason="approved" if approved else "risk_rejected",
    )


def _authorization() -> AutonomousLiveEntryAuthorization:
    """Create the sole valid TESTNET autonomous capability."""
    return AutonomousLiveEntryAuthorization(
        environment=ExchangeEnvironment.TESTNET,
        explicit_opt_in=True,
    )


@dataclass(slots=True)
class _Discovery:
    """Return one fixed, already-ranked discovery snapshot."""

    signals: tuple[Signal, ...]
    calls: int = 0

    async def discover(self, **_: object) -> Sequence[Signal]:
        """Return the configured deterministic candidates."""
        self.calls += 1
        return self.signals


@dataclass(slots=True)
class _RiskEvaluation:
    """Return current decisions in candidate-processing order."""

    decisions: dict[str, TradingDecision]
    calls: list[str] = field(default_factory=list[str])

    async def evaluate(self, *, signal: Signal) -> LiveEntryRiskEvaluation:
        """Record decision-time evaluation for one candidate."""
        self.calls.append(signal.symbol)
        return LiveEntryRiskEvaluation(
            decision=self.decisions[signal.symbol],
            has_existing_position=False,
        )


@dataclass(slots=True)
class _Execution:
    """Return typed protected-entry outcomes strictly sequentially."""

    statuses: dict[str, AutonomousLiveEntryExecutionStatus]
    calls: list[str] = field(default_factory=list[str])
    active: int = 0
    maximum_active: int = 0

    async def execute(
        self,
        *,
        intent: AutonomousLiveEntryIntent,
        authorization: AutonomousLiveEntryAuthorization | None,
    ) -> AutonomousLiveEntryExecutionResult:
        """Record one mutation boundary without exchange I/O."""
        assert authorization is not None
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        self.calls.append(intent.symbol)
        try:
            await asyncio.sleep(0)
            status = self.statuses[intent.symbol]
            if status is AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED:
                return AutonomousLiveEntryExecutionResult(
                    status=status,
                    decision=_decision(signal=intent.signal),
                    order=Order(
                        order_id=f"order-{intent.symbol}",
                        symbol=intent.symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        status=OrderStatus.FILLED,
                        quantity=Decimal("1"),
                        executed_quantity=Decimal("1"),
                        created_at=_NOW,
                        updated_at=_NOW,
                    ),
                )
            return AutonomousLiveEntryExecutionResult(
                status=status,
                decision=_decision(signal=intent.signal),
            )
        finally:
            self.active -= 1


def _executor(
    *,
    signals: tuple[Signal, ...],
    decisions: dict[str, TradingDecision],
    statuses: dict[str, AutonomousLiveEntryExecutionStatus],
) -> tuple[AutonomousLiveTradingCycleExecutor, _RiskEvaluation, _Execution]:
    """Build the complete production-orchestration boundary with fakes."""
    risk = _RiskEvaluation(decisions=decisions)
    execution = _Execution(statuses=statuses)
    return (
        AutonomousLiveTradingCycleExecutor(
            discovery_service=_Discovery(signals=signals),
            risk_evaluation_service=risk,
            intent_service=AutonomousLiveEntryIntentService(
                execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
                environment=ExchangeEnvironment.TESTNET,
            ),
            execution_service=execution,
            authorization=_authorization(),
            quote_asset="USDT",
            max_symbols=3,
            top_n=3,
            strategy_type=StrategyType.EMA_CROSS,
        ),
        risk,
        execution,
    )


def test_cycle_continues_after_safe_rejection_and_is_strictly_sequential() -> None:
    """A rejected BTC decision must not prevent later safe ETH evaluation."""
    btc = _signal(symbol="BTCUSDT")
    eth = _signal(symbol="ETHUSDT")
    executor, risk, execution = _executor(
        signals=(btc, eth),
        decisions={
            btc.symbol: _decision(signal=btc, approved=False),
            eth.symbol: _decision(signal=eth),
        },
        statuses={
            eth.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        },
    )

    results = asyncio.run(
        executor.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert risk.calls == ["BTCUSDT", "ETHUSDT"]
    assert execution.calls == ["ETHUSDT"]
    assert execution.maximum_active == 1
    assert [result.executed for result in results] == [False, True]


def test_unsafe_entry_stops_later_ranked_candidates() -> None:
    """Uncertain BTC state must block ETH before its next risk read."""
    btc = _signal(symbol="BTCUSDT")
    eth = _signal(symbol="ETHUSDT")
    executor, risk, execution = _executor(
        signals=(btc, eth),
        decisions={
            btc.symbol: _decision(signal=btc),
            eth.symbol: _decision(signal=eth),
        },
        statuses={btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTION_UNSAFE},
    )

    with pytest.raises(AutonomousLiveCycleUnsafeError, match="execution_unsafe"):
        asyncio.run(executor.execute_global(interval=Interval.M15, candle_limit=100))

    assert risk.calls == ["BTCUSDT"]
    assert execution.calls == ["BTCUSDT"]


def test_terminal_exchange_rejection_allows_next_candidate_sequentially() -> None:
    """A definitive BTC rejection is safe, so ETH receives its own fresh turn."""
    btc = _signal(symbol="BTCUSDT")
    eth = _signal(symbol="ETHUSDT")
    executor, risk, execution = _executor(
        signals=(btc, eth),
        decisions={
            btc.symbol: _decision(signal=btc),
            eth.symbol: _decision(signal=eth),
        },
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.EXCHANGE_REJECTED,
            eth.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED,
        },
    )

    results = asyncio.run(
        executor.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert risk.calls == ["BTCUSDT", "ETHUSDT"]
    assert execution.calls == ["BTCUSDT", "ETHUSDT"]
    assert execution.maximum_active == 1
    assert [result.executed for result in results] == [False, True]


def test_cancellation_during_discovery_propagates_without_execution() -> None:
    """Cancellation is never converted into a safe or unsafe workflow result."""

    @dataclass(slots=True)
    class _BlockingDiscovery:
        """Block the discovery read until the test cancels its task."""

        started: asyncio.Event

        async def discover(self, **_: object) -> Sequence[Signal]:
            """Await cancellation before yielding candidates."""
            self.started.set()
            await asyncio.Event().wait()
            return ()

    async def run() -> None:
        """Cancel the global cycle at its first await point."""
        signal = _signal(symbol="BTCUSDT")
        risk = _RiskEvaluation(decisions={signal.symbol: _decision(signal=signal)})
        execution = _Execution(statuses={})
        started = asyncio.Event()
        executor = AutonomousLiveTradingCycleExecutor(
            discovery_service=_BlockingDiscovery(started=started),
            risk_evaluation_service=risk,
            intent_service=AutonomousLiveEntryIntentService(
                execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
                environment=ExchangeEnvironment.TESTNET,
            ),
            execution_service=execution,
            authorization=_authorization(),
            quote_asset="USDT",
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )
        task = asyncio.create_task(
            executor.execute_global(interval=Interval.M15, candle_limit=100)
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert risk.calls == []
        assert execution.calls == []

    asyncio.run(run())


def test_runner_pauses_after_unsafe_result_without_outer_retry() -> None:
    """An uncertain first mutation must not begin a duplicate global cycle."""
    btc = _signal(symbol="BTCUSDT")
    executor, risk, execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={btc.symbol: AutonomousLiveEntryExecutionStatus.SUBMISSION_BLOCKED},
    )
    control = TradingRuntimeControl()
    control.resume_global_cycle()
    runner = TradingRunner(
        executor=executor,
        symbol="BTCUSDT",
        interval=Interval.M15,
        trade_mode=TradeMode.LIVE,
        runtime_control=control,
        maximum_consecutive_failures=3,
        failure_retry_delay_seconds=0.01,
    )

    asyncio.run(runner.run())

    assert risk.calls == ["BTCUSDT"]
    assert execution.calls == ["BTCUSDT"]
    assert control.is_paused
    with pytest.raises(RuntimeError, match="verified position protection"):
        control.resume_global_cycle()
