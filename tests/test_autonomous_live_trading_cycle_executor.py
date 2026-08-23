"""TESTNET autonomous LIVE discovery-cycle orchestration tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
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

    async def discover(
        self,
        *,
        strategy_type: StrategyType,
        **_: object,
    ) -> Sequence[Signal]:
        """Return candidates only for the executor's explicit strategy."""
        assert strategy_type is StrategyType.EMA_CROSS
        self.calls += 1
        return self.signals


@dataclass(slots=True)
class _Reconciler:
    """Return a deterministic portfolio-adoption readiness result."""

    results: list[bool] = field(default_factory=lambda: [True])
    calls: int = 0

    async def reconcile(self) -> bool:
        """Record one required reconciliation and return the next readiness state."""
        self.calls += 1
        return self.results.pop(0) if self.results else True


@dataclass(slots=True)
class _OpportunityClaims:
    """Atomically remember closed-candle opportunity identities across executors."""

    claimed: set[tuple[str, Interval, str, datetime]] = field(
        default_factory=set[tuple[str, Interval, str, datetime]]
    )
    calls: list[tuple[str, Interval, str, datetime]] = field(
        default_factory=list[tuple[str, Interval, str, datetime]]
    )

    async def claim(self, *, signal: Signal, interval: Interval) -> bool:
        """Return true only for the first exact closed-candle identity."""
        identity = (
            signal.symbol,
            interval,
            signal.strategy_name,
            signal.generated_at,
        )
        self.calls.append(identity)
        if identity in self.claimed:
            return False
        self.claimed.add(identity)
        return True


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
    claims: _OpportunityClaims | None = None,
) -> tuple[AutonomousLiveTradingCycleExecutor, _RiskEvaluation, _Execution]:
    """Build the complete production-orchestration boundary with fakes."""
    risk = _RiskEvaluation(decisions=decisions)
    execution = _Execution(statuses=statuses)
    claim_repository = claims if claims is not None else _OpportunityClaims()
    return (
        AutonomousLiveTradingCycleExecutor(
            discovery_service=_Discovery(signals=signals),
            risk_evaluation_service=risk,
            intent_service=AutonomousLiveEntryIntentService(
                execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
                environment=ExchangeEnvironment.TESTNET,
            ),
            execution_service=execution,
            opportunity_claim_repository=claim_repository,
            authorization=_authorization(),
            live_runtime_portfolio_reconciler=_Reconciler(),
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


def test_stale_signal_is_a_safe_non_executed_result() -> None:
    """Continue ranked processing when pre-submission signal freshness expires."""
    btc = _signal(symbol="BTCUSDT")
    eth = _signal(symbol="ETHUSDT")
    executor, risk, execution = _executor(
        signals=(btc, eth),
        decisions={
            btc.symbol: _decision(signal=btc),
            eth.symbol: _decision(signal=eth),
        },
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.STALE_SIGNAL,
            eth.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED,
        },
    )

    results = asyncio.run(
        executor.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert risk.calls == ["BTCUSDT", "ETHUSDT"]
    assert execution.calls == ["BTCUSDT", "ETHUSDT"]
    assert not results[0].executed
    assert results[0].reason == "stale_signal"
    assert results[1].executed


def test_market_reference_rejection_is_a_safe_non_executed_result() -> None:
    """Continue ranked processing when no executable ticker reference is valid."""
    btc = _signal(symbol="BTCUSDT")
    eth = _signal(symbol="ETHUSDT")
    executor, risk, execution = _executor(
        signals=(btc, eth),
        decisions={
            btc.symbol: _decision(signal=btc),
            eth.symbol: _decision(signal=eth),
        },
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.MARKET_REFERENCE_REJECTED,
            eth.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED,
        },
    )

    results = asyncio.run(
        executor.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert risk.calls == ["BTCUSDT", "ETHUSDT"]
    assert execution.calls == ["BTCUSDT", "ETHUSDT"]
    assert execution.maximum_active == 1
    assert not results[0].executed
    assert results[0].reason == "market_reference_rejected"
    assert results[1].executed


def test_existing_closed_candle_claim_skips_risk_and_execution() -> None:
    """A durable claim must suppress the exact candidate before fresh risk I/O."""
    btc = _signal(symbol="BTCUSDT")
    eth = _signal(symbol="ETHUSDT")
    claims = _OpportunityClaims(
        claimed={(btc.symbol, Interval.M15, btc.strategy_name, btc.generated_at)}
    )
    executor, risk, execution = _executor(
        signals=(btc, eth),
        decisions={
            btc.symbol: _decision(signal=btc),
            eth.symbol: _decision(signal=eth),
        },
        statuses={
            eth.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED,
        },
        claims=claims,
    )

    results = asyncio.run(
        executor.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert risk.calls == ["ETHUSDT"]
    assert execution.calls == ["ETHUSDT"]
    assert [result.executed for result in results] == [False, True]
    assert results[0].reason == "closed_candle_opportunity_already_claimed"


def test_claim_survives_executor_restart_for_same_closed_candle() -> None:
    """A second executor must not retry an opportunity claimed by the first."""
    btc = _signal(symbol="BTCUSDT")
    claims = _OpportunityClaims()
    first, first_risk, first_execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={btc.symbol: AutonomousLiveEntryExecutionStatus.EXCHANGE_REJECTED},
        claims=claims,
    )

    first_results = asyncio.run(
        first.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert first_risk.calls == ["BTCUSDT"]
    assert first_execution.calls == ["BTCUSDT"]
    assert len(first_results) == 1

    second, second_risk, second_execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        },
        claims=claims,
    )
    second_results = asyncio.run(
        second.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert second_risk.calls == []
    assert second_execution.calls == []
    assert len(second_results) == 1
    assert not second_results[0].executed
    assert second_results[0].reason == "closed_candle_opportunity_already_claimed"


def test_later_closed_candle_remains_eligible_after_prior_claim() -> None:
    """Replay denial must not suppress a fresh generated-at candle identity."""
    previous = _signal(symbol="BTCUSDT")
    current = replace(previous, generated_at=_NOW + timedelta(minutes=15))
    claims = _OpportunityClaims(
        claimed={
            (
                previous.symbol,
                Interval.M15,
                previous.strategy_name,
                previous.generated_at,
            )
        }
    )
    executor, risk, execution = _executor(
        signals=(current,),
        decisions={current.symbol: _decision(signal=current)},
        statuses={
            current.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        },
        claims=claims,
    )

    results = asyncio.run(
        executor.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert risk.calls == ["BTCUSDT"]
    assert execution.calls == ["BTCUSDT"]
    assert len(results) == 1
    assert results[0].executed


def test_claim_is_durable_before_risk_failure_window() -> None:
    """A crash-like risk failure after claim must burn only that old opportunity."""

    @dataclass(slots=True)
    class _FailingRisk:
        calls: int = 0

        async def evaluate(self, *, signal: Signal) -> LiveEntryRiskEvaluation:
            del signal
            self.calls += 1
            raise RuntimeError("injected risk failure after durable claim")

    btc = _signal(symbol="BTCUSDT")
    claims = _OpportunityClaims()
    failing_risk = _FailingRisk()
    execution = _Execution(
        statuses={btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED}
    )
    first = AutonomousLiveTradingCycleExecutor(
        discovery_service=_Discovery(signals=(btc,)),
        risk_evaluation_service=failing_risk,
        intent_service=AutonomousLiveEntryIntentService(
            execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
            environment=ExchangeEnvironment.TESTNET,
        ),
        execution_service=execution,
        opportunity_claim_repository=claims,
        authorization=_authorization(),
        live_runtime_portfolio_reconciler=_Reconciler(),
        quote_asset="USDT",
        max_symbols=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )

    with pytest.raises(RuntimeError, match="injected risk failure"):
        asyncio.run(first.execute_global(interval=Interval.M15, candle_limit=100))

    assert failing_risk.calls == 1
    assert execution.calls == []

    second, second_risk, second_execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        },
        claims=claims,
    )
    results = asyncio.run(
        second.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert second_risk.calls == []
    assert second_execution.calls == []
    assert results[0].reason == "closed_candle_opportunity_already_claimed"


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
            opportunity_claim_repository=_OpportunityClaims(),
            authorization=_authorization(),
            live_runtime_portfolio_reconciler=_Reconciler(),
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


def test_required_reconciler_blocks_discovery_before_candidates() -> None:
    """Fail closed before discovery when the required portfolio read is unsafe."""
    btc = _signal(symbol="BTCUSDT")
    executor, risk, execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        },
    )
    blocked = replace(
        executor, live_runtime_portfolio_reconciler=_Reconciler(results=[False])
    )

    with pytest.raises(AutonomousLiveCycleUnsafeError, match="before discovery"):
        asyncio.run(blocked.execute_global(interval=Interval.M15, candle_limit=100))

    assert risk.calls == []
    assert execution.calls == []


def test_adoption_failure_preserves_protected_entry_and_blocks_later_candidate() -> (
    None
):
    """Keep factual protected entry truth while closing the rest of the batch."""
    btc = _signal(symbol="BTCUSDT")
    eth = _signal(symbol="ETHUSDT")
    executor, risk, execution = _executor(
        signals=(btc, eth),
        decisions={
            btc.symbol: _decision(signal=btc),
            eth.symbol: _decision(signal=eth),
        },
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED,
            eth.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED,
        },
    )
    unsafe = replace(
        executor,
        live_runtime_portfolio_reconciler=_Reconciler(results=[True, False]),
    )

    with pytest.raises(AutonomousLiveCycleUnsafeError, match="not adopted") as error:
        asyncio.run(unsafe.execute_global(interval=Interval.M15, candle_limit=100))

    assert len(error.value.completed_results) == 1
    assert error.value.completed_results[0].executed
    assert error.value.completed_results[0].order is not None
    assert error.value.completed_results[0].order.order_id == "order-BTCUSDT"
    assert risk.calls == [btc.symbol]
    assert execution.calls == [btc.symbol]


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
