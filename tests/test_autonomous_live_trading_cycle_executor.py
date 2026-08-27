"""TESTNET autonomous LIVE discovery-cycle orchestration tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from socket import gaierror

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
from botragram.exchanges.binance import BinanceRateLimitGovernor
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    AutonomousLiveEntryExecutionResult,
    AutonomousLiveEntryIntent,
    DiscoveryUniverseBatch,
    LiveEntryRiskEvaluation,
    LiveRuntimePortfolioContext,
    LiveRuntimePositionContext,
    MarketUniverseEntry,
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
    requested_symbols: list[tuple[str, ...]] = field(
        default_factory=list[tuple[str, ...]]
    )

    async def discover_symbols(
        self,
        *,
        symbols: Sequence[str],
        strategy_type: StrategyType,
        **_: object,
    ) -> Sequence[Signal]:
        """Return candidates only for the executor's explicit strategy."""
        assert strategy_type is StrategyType.EMA_CROSS
        self.calls += 1
        self.requested_symbols.append(tuple(symbols))
        return self.signals


@dataclass(slots=True)
class _Universe:
    """Return one non-consuming explicit ranked batch."""

    symbols: tuple[str, ...]
    universe_limit: int = 100
    batch_size: int = 3
    get_calls: int = 0
    completion_calls: int = 0
    returned_batches: list[DiscoveryUniverseBatch] = field(
        default_factory=list[DiscoveryUniverseBatch]
    )
    _current_batch: DiscoveryUniverseBatch | None = None

    async def get_current_batch(self) -> DiscoveryUniverseBatch:
        """Return the same batch until normal discovery completion."""
        self.get_calls += 1
        if self._current_batch is None:
            entries = tuple(
                MarketUniverseEntry(
                    symbol=symbol,
                    quote_volume=Decimal(len(self.symbols) - index),
                )
                for index, symbol in enumerate(self.symbols)
            )
            self._current_batch = DiscoveryUniverseBatch(
                entries=entries,
                universe_size=len(entries),
                rank_start=1,
                rank_end=len(entries),
            )
        self.returned_batches.append(self._current_batch)
        return self._current_batch

    def complete_batch(self, *, batch: DiscoveryUniverseBatch) -> None:
        """Record completion only for the selected batch."""
        assert batch is self._current_batch
        self.completion_calls += 1
        self._current_batch = None


def _portfolio_context(*symbols: str) -> LiveRuntimePortfolioContext:
    """Build one deterministic exact managed LIVE portfolio context."""
    return LiveRuntimePortfolioContext(
        contexts=tuple(
            LiveRuntimePositionContext(
                symbol=symbol,
                interval=Interval.M15,
                strategy_type=StrategyType.EMA_CROSS,
            )
            for symbol in symbols
        )
    )


@dataclass(slots=True)
class _Reconciler:
    """Return deterministic authoritative managed portfolio snapshots."""

    results: list[LiveRuntimePortfolioContext | None] = field(
        default_factory=lambda: [_portfolio_context()]
    )
    calls: int = 0
    last_context: LiveRuntimePortfolioContext = field(
        default_factory=_portfolio_context
    )

    async def reconcile_context(self) -> LiveRuntimePortfolioContext | None:
        """Record one required reconciliation and return its exact managed context."""
        self.calls += 1
        if not self.results:
            return self.last_context
        result = self.results.pop(0)
        if result is not None:
            self.last_context = result
        return result


@dataclass(slots=True)
class _FailingReconciler:
    """Raise one original reconciliation dependency failure."""

    error: Exception

    async def reconcile_context(self) -> LiveRuntimePortfolioContext | None:
        """Preserve the configured exception at the executor boundary."""
        raise self.error


@dataclass(slots=True)
class _RateLimitGovernor:
    """Return one deterministic optional-discovery budget decision."""

    throttled: bool
    decisions: list[bool] = field(default_factory=list[bool])
    calls: int = 0

    def should_throttle_discovery(self) -> bool:
        """Record and return the configured discovery throttle state."""
        self.calls += 1
        if self.decisions:
            return self.decisions.pop(0)
        return self.throttled


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
            discovery_universe_service=_Universe(
                symbols=tuple(signal.symbol for signal in signals),
            ),
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
            max_open_positions=3,
            strategy_type=StrategyType.EMA_CROSS,
        ),
        risk,
        execution,
    )


def test_live_executor_rejects_top_n_larger_than_ranked_batch() -> None:
    """Keep the top-N/batch relationship specific to autonomous LIVE."""
    btc = _signal(symbol="BTCUSDT")
    executor, _, _ = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={},
    )

    with pytest.raises(ValueError, match="top N must not exceed batch size"):
        replace(
            executor,
            discovery_universe_service=_Universe(
                symbols=(btc.symbol,),
                batch_size=1,
            ),
            top_n=2,
        )


@pytest.mark.parametrize("invalid", [0, -1, True])
def test_live_executor_rejects_invalid_max_open_positions(invalid: int) -> None:
    """Reject invalid autonomous LIVE portfolio-capacity configuration."""
    btc = _signal(symbol="BTCUSDT")
    executor, _, _ = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={},
    )

    with pytest.raises(ValueError, match="maximum open positions must be positive"):
        replace(executor, max_open_positions=invalid)


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
    discovery = executor.discovery_service
    assert isinstance(discovery, _Discovery)
    assert discovery.requested_symbols == [("BTCUSDT", "ETHUSDT")]


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
    universe = executor.discovery_universe_service
    assert isinstance(universe, _Universe)
    assert universe.completion_calls == 1


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
        discovery_universe_service=_Universe(
            symbols=(btc.symbol,),
            batch_size=1,
        ),
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
        max_open_positions=1,
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

        async def discover_symbols(self, **_: object) -> Sequence[Signal]:
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
        universe = _Universe(symbols=(signal.symbol,), batch_size=1)
        executor = AutonomousLiveTradingCycleExecutor(
            discovery_service=_BlockingDiscovery(started=started),
            discovery_universe_service=universe,
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
            max_open_positions=1,
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
        assert universe.completion_calls == 0

    asyncio.run(run())


def test_discovery_failure_retries_the_same_unconsumed_batch() -> None:
    """Keep the cursor fixed until a later discovery call returns normally."""

    @dataclass(slots=True)
    class _FailingOnceDiscovery:
        calls: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])

        async def discover_symbols(
            self,
            *,
            symbols: Sequence[str],
            **_: object,
        ) -> Sequence[Signal]:
            """Fail once, then complete with no actionable candidates."""
            self.calls.append(tuple(symbols))
            if len(self.calls) == 1:
                raise RuntimeError("injected candle failure")
            return ()

    btc = _signal(symbol="BTCUSDT")
    executor, risk, execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={},
    )
    discovery = _FailingOnceDiscovery()
    retrying = replace(executor, discovery_service=discovery)
    universe = retrying.discovery_universe_service
    assert isinstance(universe, _Universe)

    with pytest.raises(RuntimeError, match="injected candle failure"):
        asyncio.run(retrying.execute_global(interval=Interval.M15, candle_limit=100))

    assert universe.completion_calls == 0
    results = asyncio.run(
        retrying.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert results == ()
    assert discovery.calls == [("BTCUSDT",), ("BTCUSDT",)]
    assert universe.returned_batches[0] is universe.returned_batches[1]
    assert universe.completion_calls == 1
    assert risk.calls == []
    assert execution.calls == []


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
        executor, live_runtime_portfolio_reconciler=_Reconciler(results=[None])
    )

    with pytest.raises(AutonomousLiveCycleUnsafeError, match="before discovery"):
        asyncio.run(blocked.execute_global(interval=Interval.M15, candle_limit=100))

    assert risk.calls == []
    assert execution.calls == []


def test_transient_reconciliation_failure_is_not_wrapped_as_cycle_unsafe() -> None:
    """Allow the runner to classify a DNS outage as unattended connectivity loss."""
    btc = _signal(symbol="BTCUSDT")
    executor, risk, execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={},
    )
    error = gaierror(11001, "configured DNS failure")
    blocked = replace(
        executor,
        live_runtime_portfolio_reconciler=_FailingReconciler(error=error),
    )

    with pytest.raises(gaierror) as raised:
        asyncio.run(blocked.execute_global(interval=Interval.M15, candle_limit=100))

    assert raised.value is error
    assert not isinstance(raised.value, AutonomousLiveCycleUnsafeError)
    assert risk.calls == []
    assert execution.calls == []


def test_rate_limit_gate_runs_after_reconciliation_without_scanning() -> None:
    """Preserve safety reconciliation while withholding optional new entries."""
    btc = _signal(symbol="BTCUSDT")
    claims = _OpportunityClaims()
    executor, risk, execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        },
        claims=claims,
    )
    reconciler = _Reconciler()
    governor = _RateLimitGovernor(throttled=True)
    blocked = replace(
        executor,
        live_runtime_portfolio_reconciler=reconciler,
        discovery_rate_limit_governor=governor,
    )
    universe = blocked.discovery_universe_service
    discovery = blocked.discovery_service
    assert isinstance(universe, _Universe)
    assert isinstance(discovery, _Discovery)

    report = asyncio.run(
        blocked.execute_global_report(interval=Interval.M15, candle_limit=100)
    )

    assert report.skipped_rate_limit
    assert report.skipped_capacity is False
    assert report.scanned_count == 0
    assert reconciler.calls == 1
    assert governor.calls == 1
    assert universe.get_calls == 0
    assert discovery.calls == 0
    assert claims.calls == []
    assert risk.calls == []
    assert execution.calls == []


def test_retry_after_never_bypasses_safety_reconciliation() -> None:
    """Run authoritative recovery before applying an optional-work cooldown."""
    btc = _signal(symbol="BTCUSDT")
    executor, risk, execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        },
    )
    governor = BinanceRateLimitGovernor()
    governor.observe_response(
        headers={},
        status=429,
        retry_after_seconds=60,
    )
    reconciler = _Reconciler()
    blocked = replace(
        executor,
        live_runtime_portfolio_reconciler=reconciler,
        discovery_rate_limit_governor=governor,
    )

    report = asyncio.run(
        blocked.execute_global_report(interval=Interval.M15, candle_limit=100)
    )

    assert report.skipped_rate_limit
    assert reconciler.calls == 1
    assert risk.calls == []
    assert execution.calls == []


def test_budget_crossing_during_risk_skips_entry_without_trading_error() -> None:
    """Recheck headroom immediately before mutation after discovery REST work."""
    btc = _signal(symbol="BTCUSDT")
    claims = _OpportunityClaims()
    executor, risk, execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        },
        claims=claims,
    )
    governor = _RateLimitGovernor(
        throttled=True,
        decisions=[False, False, True],
    )
    guarded = replace(
        executor,
        discovery_rate_limit_governor=governor,
    )

    report = asyncio.run(
        guarded.execute_global_report(interval=Interval.M15, candle_limit=100)
    )

    assert report.skipped_rate_limit
    assert report.batch is not None
    assert report.scanned_count == 1
    assert len(report.results) == 1
    assert report.results[0].executed is False
    assert report.results[0].reason == "skipped_rate_limit"
    assert governor.calls == 3
    assert [identity[0] for identity in claims.calls] == ["BTCUSDT"]
    assert risk.calls == ["BTCUSDT"]
    assert execution.calls == []


@pytest.mark.parametrize("maximum", [1, 3, 5])
def test_full_authoritative_portfolio_skips_discovery_before_any_claim(
    maximum: int,
) -> None:
    """A full reconciled portfolio must avoid all expensive discovery and claims."""
    btc = _signal(symbol="BTCUSDT")
    claims = _OpportunityClaims()
    executor, risk, execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        },
        claims=claims,
    )
    symbols = tuple(f"OPEN{index}USDT" for index in range(maximum))
    reconciler = _Reconciler(results=[_portfolio_context(*symbols)])
    blocked = replace(
        executor,
        live_runtime_portfolio_reconciler=reconciler,
        max_open_positions=maximum,
    )
    universe = blocked.discovery_universe_service
    discovery = blocked.discovery_service
    assert isinstance(universe, _Universe)
    assert isinstance(discovery, _Discovery)

    report = asyncio.run(
        blocked.execute_global_report(interval=Interval.M15, candle_limit=100)
    )

    assert report.results == ()
    assert report.skipped_capacity is True
    assert report.batch is None
    assert report.scanned_count == 0
    assert report.signals == ()
    assert report.stopped_by_capacity is False
    assert reconciler.calls == 1
    assert universe.get_calls == 0
    assert universe.completion_calls == 0
    assert discovery.calls == 0
    assert claims.calls == []
    assert risk.calls == []
    assert execution.calls == []


def test_zero_to_three_fills_sequentially_without_fourth_candidate_claim() -> None:
    """Fill three slots one at a time and stop before claiming a fourth candidate."""
    btc = _signal(symbol="BTCUSDT")
    eth = _signal(symbol="ETHUSDT")
    sol = _signal(symbol="SOLUSDT")
    xrp = _signal(symbol="XRPUSDT")
    claims = _OpportunityClaims()
    executor, risk, execution = _executor(
        signals=(btc, eth, sol, xrp),
        decisions={
            signal.symbol: _decision(signal=signal) for signal in (btc, eth, sol, xrp)
        },
        statuses={
            signal.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
            for signal in (btc, eth, sol, xrp)
        },
        claims=claims,
    )
    reconciler = _Reconciler(
        results=[
            _portfolio_context(),
            _portfolio_context("BTCUSDT"),
            _portfolio_context("BTCUSDT", "ETHUSDT"),
            _portfolio_context("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        ]
    )
    bounded = replace(
        executor,
        discovery_universe_service=_Universe(
            symbols=(btc.symbol, eth.symbol, sol.symbol, xrp.symbol),
            batch_size=4,
        ),
        live_runtime_portfolio_reconciler=reconciler,
        max_symbols=4,
        max_open_positions=3,
        top_n=4,
    )

    report = asyncio.run(
        bounded.execute_global_report(interval=Interval.M15, candle_limit=100)
    )

    assert [result.executed for result in report.results] == [True, True, True]
    assert report.batch is not None
    assert report.scanned_count == 4
    assert tuple(signal.symbol for signal in report.signals) == (
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
    )
    assert report.stopped_by_capacity is True
    assert [identity[0] for identity in claims.calls] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
    ]
    assert risk.calls == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert execution.calls == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert execution.maximum_active == 1
    assert reconciler.calls == 4


def test_partial_capacity_reopens_discovery_and_refills_one_slot() -> None:
    """A later 3-to-2 reconciliation must resume discovery and refill to three."""
    btc = _signal(symbol="BTCUSDT")
    claims = _OpportunityClaims()
    executor, risk, execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={
            btc.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
        },
        claims=claims,
    )
    reconciler = _Reconciler(
        results=[
            _portfolio_context("OPEN1USDT", "OPEN2USDT", "OPEN3USDT"),
            _portfolio_context("OPEN1USDT", "OPEN2USDT"),
            _portfolio_context("OPEN1USDT", "OPEN2USDT", "BTCUSDT"),
        ]
    )
    bounded = replace(
        executor,
        live_runtime_portfolio_reconciler=reconciler,
        max_open_positions=3,
    )
    universe = bounded.discovery_universe_service
    assert isinstance(universe, _Universe)

    first = asyncio.run(bounded.execute_global(interval=Interval.M15, candle_limit=100))
    second = asyncio.run(
        bounded.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert first == ()
    assert [result.executed for result in second] == [True]
    assert universe.get_calls == 1
    assert universe.completion_calls == 1
    assert [identity[0] for identity in claims.calls] == ["BTCUSDT"]
    assert risk.calls == ["BTCUSDT"]
    assert execution.calls == ["BTCUSDT"]
    assert reconciler.calls == 3


def test_post_entry_capacity_fill_stops_before_later_candidate_claim() -> None:
    """Stop the candidate batch immediately after exact adoption fills capacity."""
    btc = _signal(symbol="BTCUSDT")
    eth = _signal(symbol="ETHUSDT")
    sol = _signal(symbol="SOLUSDT")
    claims = _OpportunityClaims()
    executor, risk, execution = _executor(
        signals=(btc, eth, sol),
        decisions={
            btc.symbol: _decision(signal=btc, approved=False),
            eth.symbol: _decision(signal=eth),
            sol.symbol: _decision(signal=sol),
        },
        statuses={
            eth.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED,
            sol.symbol: AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED,
        },
        claims=claims,
    )
    reconciler = _Reconciler(
        results=[
            _portfolio_context("OPEN1USDT", "OPEN2USDT"),
            _portfolio_context("OPEN1USDT", "OPEN2USDT", "ETHUSDT"),
        ]
    )
    bounded = replace(
        executor,
        live_runtime_portfolio_reconciler=reconciler,
        max_open_positions=3,
    )

    results = asyncio.run(
        bounded.execute_global(interval=Interval.M15, candle_limit=100)
    )

    assert [result.executed for result in results] == [False, True]
    assert [identity[0] for identity in claims.calls] == ["BTCUSDT", "ETHUSDT"]
    assert risk.calls == ["BTCUSDT", "ETHUSDT"]
    assert execution.calls == ["ETHUSDT"]
    assert reconciler.calls == 2


def test_over_capacity_authoritative_portfolio_is_managed_but_adds_no_exposure() -> (
    None
):
    """Treat an already over-capacity exact portfolio as full without truncating it."""
    btc = _signal(symbol="BTCUSDT")
    claims = _OpportunityClaims()
    executor, risk, execution = _executor(
        signals=(btc,),
        decisions={btc.symbol: _decision(signal=btc)},
        statuses={},
        claims=claims,
    )
    reconciler = _Reconciler(
        results=[_portfolio_context("AUSDT", "BUSDT", "CUSDT", "DUSDT")]
    )
    blocked = replace(
        executor,
        live_runtime_portfolio_reconciler=reconciler,
        max_open_positions=3,
    )

    assert (
        asyncio.run(blocked.execute_global(interval=Interval.M15, candle_limit=100))
        == ()
    )
    assert (
        reconciler.last_context.contexts
        == _portfolio_context("AUSDT", "BUSDT", "CUSDT", "DUSDT").contexts
    )
    assert claims.calls == []
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
        live_runtime_portfolio_reconciler=_Reconciler(
            results=[_portfolio_context(), None]
        ),
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
