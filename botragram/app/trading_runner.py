"""
Botragram

Description:
    Cancellable trading-cycle runtime orchestration.

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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from time import monotonic
from typing import Final, Protocol, runtime_checkable

from botragram.app.global_discovery_telemetry import (
    GlobalDiscoverySnapshot,
    GlobalDiscoveryTelemetry,
)
from botragram.app.runtime_control import TradingRuntimeControl

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    AutonomousLiveEntryExecutionStatus,
    Interval,
    LiveMarketStreamLifecycleStatus,
    LivePortfolioRecoveryStatus,
    LiveRuntimeHealthStatus,
    OrderType,
    SignalType,
    StrategyType,
    TradeMode,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    AutonomousLiveEntryExecutionResult,
    AutonomousLiveEntryIntent,
    AutonomousLiveEntryIntentResult,
    DiscoveryUniverseBatch,
    ExecutionAuthorization,
    LiveEntryRiskEvaluation,
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveProtectionMonitorState,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimeHealthSnapshot,
    LiveRuntimePortfolioContext,
    LiveRuntimePositionContext,
    Signal,
    TradingDecision,
    TradingResult,
)

__all__ = [
    "AutonomousPaperTradingCycleExecutor",
    "AutonomousLiveCycleUnsafeError",
    "AutonomousLiveTradingCycleExecutor",
    "GlobalDiscoveryCycleReport",
    "GlobalTradingCycleExecutor",
    "HumanConfirmedPaperTradingCycleExecutor",
    "MultiContextActivationPreconditionProvider",
    "MultiContextRunnerActivationPreconditions",
    "SingleSymbolTradingCycleExecutor",
    "TradingCycleExecutor",
    "TradingRunner",
]


# =============================================================================
# Constants
# =============================================================================
_DEFAULT_CANDLE_LIMIT: Final[int] = 100
_DEFAULT_PAPER_ACCOUNT_BALANCE: Final[Decimal] = Decimal("10000")
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS: Final[float] = 30.0
_DEFAULT_AUTONOMOUS_LIVE_HEALTH_CHECK_INTERVAL_SECONDS: Final[float] = 1.0
_RESULT_REASON_UNAVAILABLE: Final[str] = "No reason provided"
_AUTONOMOUS_LIVE_CLOSED_CANDLE_REPLAY_REASON: Final[str] = (
    "closed_candle_opportunity_already_claimed"
)
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class _RecoveredPortfolioReconciliationRequiredError(RuntimeError):
    """Stop a batch when recovered LIVE portfolio state becomes stale."""


class AutonomousLiveCycleUnsafeError(RuntimeError):
    """Stop autonomous LIVE while preserving completed candidate truth."""

    def __init__(
        self,
        message: str,
        *,
        completed_results: Sequence[TradingResult] = (),
    ) -> None:
        """Initialize an unsafe cycle with already completed candidate results."""
        super().__init__(message)
        self.completed_results = tuple(completed_results)


@dataclass(slots=True, kw_only=True, frozen=True)
class GlobalDiscoveryCycleReport:
    """Describe one completed autonomous global-discovery cycle factually."""

    results: tuple[TradingResult, ...] = ()
    batch: DiscoveryUniverseBatch | None = None
    signals: tuple[Signal, ...] = ()
    skipped_capacity: bool = False
    stopped_by_capacity: bool = False

    def __post_init__(self) -> None:
        """Reject contradictory capacity and discovery facts."""
        if self.skipped_capacity and (
            self.batch is not None
            or self.signals
            or self.results
            or self.stopped_by_capacity
        ):
            raise ValueError(
                "Capacity-skipped global discovery must not contain scan results"
            )
        if self.batch is None and self.signals:
            raise ValueError("Discovered signals require a ranked universe batch")
        if self.stopped_by_capacity and self.batch is None:
            raise ValueError(
                "Capacity-stopped discovery requires a ranked universe batch"
            )

    @property
    def scanned_count(self) -> int:
        """Return the exact number of ranked symbols scanned by this cycle."""
        return len(self.batch.entries) if self.batch is not None else 0


class _AutonomousLiveRuntimeHealthUnsafeError(RuntimeError):
    """Represent one local recovered-runtime health condition fail-closed."""

    def __init__(self, *, snapshot: LiveRuntimeHealthSnapshot) -> None:
        reason = snapshot.reason.value if snapshot.reason is not None else "unknown"
        super().__init__(
            f"Autonomous LIVE runtime health is {snapshot.status.value}: {reason}"
        )
        self.snapshot = snapshot


# =============================================================================
# Runtime Contracts
# =============================================================================
class _AutonomousLiveOpportunityClaimProvider(Protocol):
    """Atomically deny replay of one exact autonomous LIVE closed candle."""

    async def claim(self, *, signal: Signal, interval: Interval) -> bool:
        """Return true only when the closed-candle identity was newly claimed."""
        ...


class TradingCycleExecutor(Protocol):
    """Execute one complete runtime trading cycle."""

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
    ) -> Sequence[TradingResult]:
        """Execute and return all results produced by one runtime cycle."""
        ...


@runtime_checkable
class GlobalTradingCycleExecutor(Protocol):
    """Execute one market-wide cycle independent of recovered contexts."""

    async def execute_global(
        self,
        *,
        interval: Interval,
        candle_limit: int,
    ) -> Sequence[TradingResult]:
        """Execute one bounded global discovery and entry cycle."""
        ...


@runtime_checkable
class _GlobalDiscoveryCycleReportingExecutor(Protocol):
    """Return typed global-discovery facts without changing legacy results."""

    async def execute_global_report(
        self,
        *,
        interval: Interval,
        candle_limit: int,
    ) -> GlobalDiscoveryCycleReport:
        """Execute one global cycle and return its immutable discovery report."""
        ...


class SingleSymbolExecutionProvider(Protocol):
    """Execute the existing single-symbol trading workflow."""

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
        """Execute and return one single-symbol trading result."""
        ...


class AutonomousPaperExecutionProvider(Protocol):
    """Execute a bounded autonomous PAPER opportunity cycle."""

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
        initial_balance: Decimal | None = None,
    ) -> Sequence[TradingResult]:
        """Discover and execute ranked PAPER candidates."""
        ...


class OpportunityDiscoveryProvider(Protocol):
    """Discover deterministic actionable market opportunities."""

    async def discover_symbols(
        self,
        *,
        symbols: Sequence[str],
        interval: Interval,
        candle_limit: int,
        top_n: int,
        strategy_type: StrategyType,
    ) -> Sequence[Signal]:
        """Return ranked actionable signals for one explicit symbol batch."""
        ...


class DiscoveryUniverseProvider(Protocol):
    """Own process-local ranked discovery batches for autonomous LIVE."""

    universe_limit: int
    batch_size: int

    async def get_current_batch(self) -> DiscoveryUniverseBatch:
        """Return the current batch without consuming it."""
        ...

    def complete_batch(self, *, batch: DiscoveryUniverseBatch) -> None:
        """Advance after normal discovery completion."""
        ...


class AutonomousLiveIntentProvider(Protocol):
    """Authorize one fresh decision as a transient autonomous LIVE intent."""

    def authorize(
        self,
        *,
        decision: TradingDecision,
        interval: Interval,
        strategy_type: StrategyType,
        authorization: AutonomousLiveEntryAuthorization | None,
    ) -> AutonomousLiveEntryIntentResult:
        """Return a typed pre-mutation intent outcome."""
        ...


class LiveEntryRiskEvaluationProvider(Protocol):
    """Provide current portfolio-aware risk decisions for one signal."""

    async def evaluate(self, *, signal: Signal) -> LiveEntryRiskEvaluation:
        """Return the canonical current decision evaluation."""
        ...


class AutonomousLiveEntryExecutionProvider(Protocol):
    """Execute one authorized TESTNET protected entry."""

    async def execute(
        self,
        *,
        intent: AutonomousLiveEntryIntent,
        authorization: AutonomousLiveEntryAuthorization | None,
    ) -> AutonomousLiveEntryExecutionResult:
        """Return the typed protected-entry execution outcome."""
        ...


class HumanConfirmedPaperExecutionProvider(Protocol):
    """Prepare bounded PAPER opportunities for explicit human approval."""

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> Sequence[ExecutionAuthorization]:
        """Return newly prepared non-executed authorizations."""
        ...


class TradingRuntimeObserver(Protocol):
    """Observe runtime lifecycle without controlling trading decisions."""

    async def on_started(self) -> None:
        """Observe runtime startup."""
        ...

    async def on_cycle_completed(self, *, result: TradingResult) -> None:
        """Observe a completed trading cycle."""
        ...

    async def on_cycle_failed(
        self,
        *,
        error: Exception,
        consecutive_failures: int,
        maximum_failures: int,
    ) -> None:
        """Observe a failed cycle before retry or propagation."""
        ...

    async def on_stopped(self) -> None:
        """Observe runtime shutdown."""
        ...


class _AutonomousLiveRuntimeRecovery(Protocol):
    """Attempt existing runtime recovery without replaying a candidate."""

    async def recover(self) -> bool:
        """Return whether complete LIVE runtime readiness was restored safely."""
        ...


class _LiveRuntimeHealthProvider(Protocol):
    """Expose read-only recovered LIVE health without granting authorization."""

    def get_snapshot(self) -> LiveRuntimeHealthSnapshot:
        """Return the current local runtime-health snapshot."""
        ...


class _LiveRuntimePortfolioReconciler(Protocol):
    """Reconcile authoritative LIVE exposure into local management ownership."""

    async def reconcile_context(self) -> LiveRuntimePortfolioContext | None:
        """Return the exact managed portfolio, or none when reconciliation is unsafe."""
        ...


class MultiContextActivationPreconditionProvider(Protocol):
    """Build current LIVE multi-context activation state without runner I/O."""

    def get_multi_context_activation_preconditions(
        self,
        *,
        runtime_is_stopping: bool,
    ) -> MultiContextRunnerActivationPreconditions | None:
        """Return current exact multi-context activation state."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class MultiContextRunnerActivationPreconditions:
    """Describe whether a recovered context portfolio can run safely.

    The value object separates verified runtime substrate from authorization.
    It deliberately does not resume a runner or select a primary context.
    """

    portfolio_status: LivePortfolioRecoveryStatus
    contexts: tuple[LiveRuntimePositionContext, ...]
    stream_states: tuple[LiveMarketStreamState, ...]
    monitor_states: tuple[LiveProtectionMonitorState, ...]
    live_management_authorization: LiveRecoveredPositionManagementAuthorization
    runtime_is_paused: bool
    runtime_is_stopping: bool

    @property
    def runtime_representation_valid(self) -> bool:
        """Return whether contexts match their typed recovery outcome."""
        context_count = len(self.contexts)
        return (
            self.portfolio_status is LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE
            and context_count == 1
        ) or (
            self.portfolio_status is LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE
            and context_count > 1
        )

    @property
    def stream_substrate_ready(self) -> bool:
        """Return whether every context has exactly one ready owned stream."""
        expected_identities = frozenset(
            LiveMarketStreamIdentity.from_runtime_context(context=context)
            for context in self.contexts
        )
        actual_identities = tuple(
            stream_state.identity for stream_state in self.stream_states
        )
        return (
            bool(expected_identities)
            and len(actual_identities) == len(set(actual_identities))
            and frozenset(actual_identities) == expected_identities
            and all(
                stream_state.lifecycle_status is LiveMarketStreamLifecycleStatus.RUNNING
                and stream_state.first_tick_received
                for stream_state in self.stream_states
            )
        )

    @property
    def protection_monitoring_ready(self) -> bool:
        """Return whether every context has one active healthy exact monitor."""
        expected_contexts = frozenset(self.contexts)
        actual_contexts = tuple(
            monitor_state.context for monitor_state in self.monitor_states
        )
        return (
            bool(expected_contexts)
            and len(actual_contexts) == len(set(actual_contexts))
            and frozenset(actual_contexts) == expected_contexts
            and all(
                monitor_state.is_active and monitor_state.failure_type is None
                for monitor_state in self.monitor_states
            )
        )

    @property
    def is_eligible(self) -> bool:
        """Return whether all future runner-activation requirements are met."""
        return (
            self.runtime_representation_valid
            and self.stream_substrate_ready
            and self.protection_monitoring_ready
            and self.live_management_authorization.authorizes_contexts(
                contexts=self.contexts,
            )
            and not self.runtime_is_paused
            and not self.runtime_is_stopping
        )

    @property
    def can_activate(self) -> bool:
        """Return whether readiness and authorization permit a paused activation."""
        return (
            self.runtime_representation_valid
            and self.stream_substrate_ready
            and self.protection_monitoring_ready
            and self.live_management_authorization.authorizes_contexts(
                contexts=self.contexts,
            )
            and not self.runtime_is_stopping
        )


@dataclass(slots=True, kw_only=True, frozen=True)
class SingleSymbolTradingCycleExecutor:
    """Adapt the established single-symbol service to the runtime contract."""

    trading_service: SingleSymbolExecutionProvider

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
    ) -> Sequence[TradingResult]:
        """Execute the existing single-symbol workflow as one cycle result."""
        if live_management_authorization is None:
            result = await self.trading_service.execute(
                symbol=symbol,
                interval=interval,
                strategy_type=strategy_type,
                candle_limit=candle_limit,
                current_drawdown_pct=current_drawdown_pct,
                order_type=order_type,
                price=price,
                account_balance_override=account_balance_override,
                synchronize_position=synchronize_position,
                submit_order=submit_order,
            )
            return (result,)

        result = await self.trading_service.execute(
            symbol=symbol,
            interval=interval,
            strategy_type=strategy_type,
            live_management_authorization=live_management_authorization,
            candle_limit=candle_limit,
            current_drawdown_pct=current_drawdown_pct,
            order_type=order_type,
            price=price,
            account_balance_override=account_balance_override,
            synchronize_position=synchronize_position,
            submit_order=submit_order,
        )
        return (result,)


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousPaperTradingCycleExecutor:
    """Adapt autonomous discovery to a runtime cycle with PAPER-only safety."""

    autonomous_execution_service: AutonomousPaperExecutionProvider
    quote_asset: str
    max_symbols: int
    top_n: int

    def __post_init__(self) -> None:
        """Normalize and validate static autonomous-discovery inputs."""
        normalized_quote_asset = self.quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Autonomous execution quote asset must not be empty")

        if self.max_symbols <= 0:
            raise ValueError("Autonomous execution maximum symbols must be positive")

        if self.top_n <= 0:
            raise ValueError("Autonomous execution top N must be positive")

        object.__setattr__(self, "quote_asset", normalized_quote_asset)

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
    ) -> Sequence[TradingResult]:
        """Execute one bounded PAPER discovery cycle without order submission."""
        del (
            symbol,
            strategy_type,
            live_management_authorization,
            current_drawdown_pct,
            order_type,
            price,
            synchronize_position,
        )

        if submit_order:
            raise RuntimeError("Autonomous execution is restricted to paper mode")

        return await self.autonomous_execution_service.execute(
            quote_asset=self.quote_asset,
            interval=interval,
            candle_limit=candle_limit,
            max_symbols=self.max_symbols,
            top_n=self.top_n,
            initial_balance=account_balance_override,
        )


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousLiveTradingCycleExecutor:
    """Compose ranked TESTNET discovery with sequential protected LIVE entry.

    It has no exchange client dependency. Discovery binds each candidate to
    the executor's explicit closed-candle strategy context before the durable
    replay claim, fresh canonical risk decision, intent authorization, and
    protected-entry mutation boundary.
    """

    discovery_service: OpportunityDiscoveryProvider
    discovery_universe_service: DiscoveryUniverseProvider
    risk_evaluation_service: LiveEntryRiskEvaluationProvider
    intent_service: AutonomousLiveIntentProvider
    execution_service: AutonomousLiveEntryExecutionProvider
    opportunity_claim_repository: _AutonomousLiveOpportunityClaimProvider
    authorization: AutonomousLiveEntryAuthorization
    quote_asset: str
    max_symbols: int
    top_n: int
    max_open_positions: int
    strategy_type: StrategyType
    live_runtime_portfolio_reconciler: _LiveRuntimePortfolioReconciler

    def __post_init__(self) -> None:
        """Validate the static TESTNET discovery composition."""
        quote_asset = self.quote_asset.strip().upper()
        if not quote_asset:
            raise ValueError("Autonomous LIVE quote asset must not be empty")
        if self.max_symbols <= 0:
            raise ValueError("Autonomous LIVE maximum symbols must be positive")
        if self.top_n <= 0:
            raise ValueError("Autonomous LIVE top N must be positive")
        if isinstance(self.max_open_positions, bool) or self.max_open_positions <= 0:
            raise ValueError("Autonomous LIVE maximum open positions must be positive")
        if self.top_n > self.discovery_universe_service.batch_size:
            raise ValueError("Autonomous LIVE top N must not exceed batch size")
        if not self.authorization.new_live_entry_allowed:
            raise ValueError("Autonomous LIVE requires TESTNET entry authorization")
        object.__setattr__(self, "quote_asset", quote_asset)

    async def execute_global(
        self,
        *,
        interval: Interval,
        candle_limit: int,
    ) -> Sequence[TradingResult]:
        """Preserve the established sequence-returning global executor contract."""
        report = await self.execute_global_report(
            interval=interval,
            candle_limit=candle_limit,
        )
        return report.results

    async def execute_global_report(
        self,
        *,
        interval: Interval,
        candle_limit: int,
    ) -> GlobalDiscoveryCycleReport:
        """Discover, process, and report one bounded autonomous LIVE cycle."""
        portfolio = await self._reconcile_live_runtime_portfolio()
        if portfolio is None:
            raise AutonomousLiveCycleUnsafeError(
                "Autonomous LIVE portfolio reconciliation failed before discovery"
            )
        if self._portfolio_is_full(portfolio=portfolio):
            return GlobalDiscoveryCycleReport(skipped_capacity=True)

        batch = await self.discovery_universe_service.get_current_batch()
        signals = tuple(
            await self.discovery_service.discover_symbols(
                symbols=tuple(entry.symbol for entry in batch.entries),
                interval=interval,
                candle_limit=candle_limit,
                top_n=self.top_n,
                strategy_type=self.strategy_type,
            )
        )
        self.discovery_universe_service.complete_batch(batch=batch)
        results: list[TradingResult] = []
        stopped_by_capacity = False

        for signal in signals:
            if self._portfolio_is_full(portfolio=portfolio):
                stopped_by_capacity = True
                break

            claimed = await self.opportunity_claim_repository.claim(
                signal=signal,
                interval=interval,
            )
            if not claimed:
                results.append(self._closed_candle_replay_result(signal=signal))
                continue

            evaluation = await self.risk_evaluation_service.evaluate(signal=signal)
            decision = evaluation.decision
            intent_result = self.intent_service.authorize(
                decision=decision,
                interval=interval,
                strategy_type=self.strategy_type,
                authorization=self.authorization,
            )
            if intent_result.intent is None:
                results.append(
                    self._non_executed_result(
                        decision=decision,
                        reason=intent_result.status.value,
                    )
                )
                continue

            execution_result = await self.execution_service.execute(
                intent=intent_result.intent,
                authorization=self.authorization,
            )
            results.append(self._to_trading_result(result=execution_result))

            if (
                execution_result.status
                is AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
            ):
                reconciled_portfolio = await self._reconcile_live_runtime_portfolio()
                if reconciled_portfolio is None:
                    raise AutonomousLiveCycleUnsafeError(
                        "Autonomous LIVE protected entry was not adopted into "
                        "runtime management",
                        completed_results=results,
                    )
                portfolio = reconciled_portfolio
                if self._portfolio_is_full(portfolio=portfolio):
                    stopped_by_capacity = True
                    break

            if execution_result.status in {
                AutonomousLiveEntryExecutionStatus.SUBMISSION_BLOCKED,
                AutonomousLiveEntryExecutionStatus.EXECUTION_UNSAFE,
            }:
                raise AutonomousLiveCycleUnsafeError(
                    "Autonomous LIVE protected entry requires recovery: "
                    f"{execution_result.status.value}"
                )

        return GlobalDiscoveryCycleReport(
            results=tuple(results),
            batch=batch,
            signals=signals,
            stopped_by_capacity=stopped_by_capacity,
        )

    async def _reconcile_live_runtime_portfolio(
        self,
    ) -> LiveRuntimePortfolioContext | None:
        """Return authoritative managed exposure before discovery and after entry."""
        return await self.live_runtime_portfolio_reconciler.reconcile_context()

    def _portfolio_is_full(self, *, portfolio: LiveRuntimePortfolioContext) -> bool:
        """Return whether the authoritative managed portfolio has no entry capacity."""
        return len(portfolio.contexts) >= self.max_open_positions

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
    ) -> Sequence[TradingResult]:
        """Satisfy the legacy executor boundary without using a symbol context."""
        del (
            symbol,
            strategy_type,
            live_management_authorization,
            current_drawdown_pct,
            order_type,
            price,
            account_balance_override,
            synchronize_position,
        )
        if not submit_order:
            raise RuntimeError("Autonomous LIVE execution requires LIVE submission")
        return await self.execute_global(
            interval=interval,
            candle_limit=candle_limit,
        )

    @staticmethod
    def _closed_candle_replay_result(*, signal: Signal) -> TradingResult:
        """Return one safe result without repeating risk or entry work."""
        decision = TradingDecision(
            should_execute=False,
            signal=signal,
            risk_result=None,
            reason=_AUTONOMOUS_LIVE_CLOSED_CANDLE_REPLAY_REASON,
        )
        return TradingResult(
            executed=False,
            decision=decision,
            order=None,
            reason=_AUTONOMOUS_LIVE_CLOSED_CANDLE_REPLAY_REASON,
        )

    @staticmethod
    def _non_executed_result(
        *,
        decision: TradingDecision,
        reason: str,
    ) -> TradingResult:
        """Return an explicit safe no-entry workflow result."""
        return TradingResult(
            executed=False,
            decision=replace(decision, should_execute=False, reason=reason),
            order=None,
            reason=reason,
        )

    @classmethod
    def _to_trading_result(
        cls,
        *,
        result: AutonomousLiveEntryExecutionResult,
    ) -> TradingResult:
        """Translate typed entry outcomes without exposing exchange exceptions."""
        if result.decision is None:
            raise RuntimeError("Autonomous LIVE execution result lacks a decision")

        if result.status is AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED:
            return TradingResult(
                executed=True,
                decision=result.decision,
                order=result.order,
                reason=result.status.value,
            )

        return cls._non_executed_result(
            decision=result.decision,
            reason=result.status.value,
        )


@dataclass(slots=True, kw_only=True, frozen=True)
class HumanConfirmedPaperTradingCycleExecutor:
    """Adapt confirmation discovery to a PAPER runtime cycle without execution."""

    human_confirmation_service: HumanConfirmedPaperExecutionProvider
    quote_asset: str
    max_symbols: int
    top_n: int

    def __post_init__(self) -> None:
        """Normalize and validate static confirmation-discovery inputs."""
        normalized_quote_asset = self.quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Human confirmation quote asset must not be empty")

        if self.max_symbols <= 0:
            raise ValueError("Human confirmation maximum symbols must be positive")

        if self.top_n <= 0:
            raise ValueError("Human confirmation top N must be positive")

        object.__setattr__(self, "quote_asset", normalized_quote_asset)

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
    ) -> Sequence[TradingResult]:
        """Prepare human approvals while structurally rejecting order submission."""
        del (
            symbol,
            strategy_type,
            live_management_authorization,
            current_drawdown_pct,
            order_type,
            price,
            account_balance_override,
            synchronize_position,
        )

        if submit_order:
            raise RuntimeError("Human-confirmed execution is restricted to paper mode")

        authorizations = await self.human_confirmation_service.execute(
            quote_asset=self.quote_asset,
            interval=interval,
            candle_limit=candle_limit,
            max_symbols=self.max_symbols,
            top_n=self.top_n,
        )
        return tuple(
            TradingResult(
                executed=False,
                decision=TradingDecision(
                    should_execute=False,
                    signal=authorization.signal,
                    risk_result=None,
                    reason="Pending human PAPER approval",
                ),
                order=None,
                reason="Pending human PAPER approval",
            )
            for authorization in authorizations
        )


# =============================================================================
# Runtime Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
)
class TradingRunner:
    """Continuously execute trading cycles until stopped or cancelled."""

    executor: TradingCycleExecutor
    symbol: str
    interval: Interval
    trade_mode: TradeMode = TradeMode.PAPER
    candle_limit: int = _DEFAULT_CANDLE_LIMIT
    cycle_interval_seconds: float | None = None
    paper_account_balance: Decimal = _DEFAULT_PAPER_ACCOUNT_BALANCE
    runtime_control: TradingRuntimeControl = field(
        default_factory=TradingRuntimeControl,
    )
    runtime_observer: TradingRuntimeObserver | None = None
    multi_context_activation_precondition_provider: (
        MultiContextActivationPreconditionProvider | None
    ) = None
    autonomous_live_recovery_provider: _AutonomousLiveRuntimeRecovery | None = None
    live_runtime_health_provider: _LiveRuntimeHealthProvider | None = None
    maximum_autonomous_live_recovery_attempts: int = 1
    autonomous_live_health_check_interval_seconds: float = (
        _DEFAULT_AUTONOMOUS_LIVE_HEALTH_CHECK_INTERVAL_SECONDS
    )
    live_management_authorization: (
        LiveRecoveredPositionManagementAuthorization | None
    ) = None
    maximum_consecutive_failures: int = 1
    failure_retry_delay_seconds: float = 5.0
    heartbeat_interval_seconds: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    global_discovery_telemetry: GlobalDiscoveryTelemetry | None = None
    _global_discovery_telemetry: GlobalDiscoveryTelemetry | None = field(
        default=None,
        init=False,
        repr=False,
    )

    _running: bool = field(default=False, init=False)
    _stop_event: asyncio.Event = field(
        default_factory=asyncio.Event,
        init=False,
        repr=False,
    )
    _context_next_eligible_monotonic: dict[LiveRuntimePositionContext, float] = field(
        default_factory=dict[LiveRuntimePositionContext, float],
        init=False,
        repr=False,
    )
    _active_batch_context_count: int = field(default=0, init=False, repr=False)
    _global_next_eligible_monotonic: float = field(
        default=0.0,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Normalize and validate immutable runtime inputs."""
        self.symbol = self.symbol.strip().upper()

        if not self.symbol:
            raise ValueError("Trading runner symbol must not be empty")

        self.runtime_control.symbol = self.symbol

        if self.candle_limit <= 0:
            raise ValueError("Trading runner candle limit must be greater than zero")

        if self.cycle_interval_seconds is not None and self.cycle_interval_seconds <= 0:
            raise ValueError("Trading runner cycle interval must be greater than zero")

        if self.paper_account_balance <= 0:
            raise ValueError("Paper account balance must be greater than zero")

        if self.maximum_consecutive_failures <= 0:
            raise ValueError("Maximum consecutive failures must be greater than zero")

        if self.failure_retry_delay_seconds <= 0:
            raise ValueError("Failure retry delay must be greater than zero")

        if self.heartbeat_interval_seconds <= 0:
            raise ValueError("Heartbeat interval must be greater than zero")

        if self.maximum_autonomous_live_recovery_attempts <= 0:
            raise ValueError(
                "Maximum autonomous LIVE recovery attempts must be greater than zero"
            )

        if self.autonomous_live_health_check_interval_seconds <= 0:
            raise ValueError(
                "Autonomous LIVE health check interval must be greater than zero"
            )

        if (
            self.live_management_authorization is not None
            and self.trade_mode is not TradeMode.LIVE
        ):
            raise ValueError(
                "Recovered LIVE management authorization requires LIVE mode"
            )

        if self.global_discovery_telemetry is not None:
            self._global_discovery_telemetry = self.global_discovery_telemetry
        elif isinstance(self.executor, AutonomousLiveTradingCycleExecutor):
            self._global_discovery_telemetry = GlobalDiscoveryTelemetry(
                interval=self.interval,
                max_symbols=self.executor.max_symbols,
                universe_limit=self.executor.discovery_universe_service.universe_limit,
                batch_size=self.executor.discovery_universe_service.batch_size,
                top_n=self.executor.top_n,
            )

    @property
    def is_running(self) -> bool:
        """Return whether the continuous runtime loop is active."""
        return self._running

    @property
    def order_submission_enabled(self) -> bool:
        """Return whether this runtime may submit exchange orders."""
        return self.trade_mode is TradeMode.LIVE

    def get_global_discovery_snapshot(self) -> GlobalDiscoverySnapshot | None:
        """Return immutable telemetry for autonomous global discovery, if active."""
        telemetry = self._global_discovery_telemetry
        return telemetry.get_snapshot() if telemetry is not None else None

    @property
    def effective_cycle_interval_seconds(self) -> float:
        """Return the configured cadence for exactly one executable context."""
        if self._is_global_cycle_executor():
            return self._get_global_cadence_seconds()
        return self._get_context_cadence_seconds(
            context=self._get_single_cycle_context(),
        )

    async def run_once(self) -> tuple[TradingResult, ...]:
        """Execute one configured trading cycle."""
        if self._is_global_cycle_executor():
            return await self._run_global_cycle()
        context = self._get_single_cycle_context()
        self.symbol = context.symbol
        self.interval = context.interval
        return await self.run_context_cycle(context=context)

    async def run_context_cycle(
        self,
        *,
        context: LiveRuntimePositionContext,
    ) -> tuple[TradingResult, ...]:
        """Execute one cycle for an explicit immutable runtime context.

        This context-explicit boundary is deliberately independent of singular
        runtime-control access. It is not a multi-context runtime activation
        mechanism; callers that need several contexts must invoke
        ``run_context_cycles_once`` while preserving its sequential contract.

        Args:
            context: The exact symbol, interval, and strategy context to execute.

        Returns:
            All trading results produced for the supplied context.
        """
        if self._is_global_cycle_executor():
            return await self._run_global_cycle()

        live_trading = self.order_submission_enabled
        live_management_authorization = self.live_management_authorization
        if live_management_authorization is None and live_trading:
            live_management_authorization = (
                self.runtime_control.live_management_authorization
            )

        if (
            live_management_authorization is not None
            and not live_management_authorization.authorizes_context(context=context)
        ):
            raise RuntimeError(
                "Recovered LIVE management authorization does not cover runtime "
                f"context: {context.symbol}:{context.interval.value}"
            )
        _LOGGER.info(
            "Trading cycle started: symbol=%s interval=%s cadence_seconds=%s",
            context.symbol,
            context.interval.value,
            float(context.interval.seconds),
        )
        self.runtime_control.begin_cycle()

        try:
            results = tuple(
                await self._execute_context(
                    context=context,
                    live_trading=live_trading,
                    live_management_authorization=live_management_authorization,
                )
            )
        finally:
            self.runtime_control.end_cycle()

        self._log_results(context=context, results=results)

        return results

    async def run_context_cycles_once(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> tuple[TradingResult, ...]:
        """Execute explicit contexts sequentially without activating the runner.

        Args:
            contexts: Canonically ordered contexts to process exactly in order.

        Returns:
            The flattened results in the same order as their context cycles.

        Raises:
            asyncio.CancelledError: If cancellation interrupts any context cycle.
            Exception: Propagates a context-cycle failure before another context
                can begin.
        """
        if self._is_global_cycle_executor():
            return await self._run_global_cycle()

        results: list[TradingResult] = []

        for context in contexts:
            context_results = await self.run_context_cycle(context=context)
            results.extend(context_results)
            if any(
                result.decision.requires_portfolio_reconciliation
                for result in context_results
            ):
                self.runtime_control.require_portfolio_reconciliation(
                    context=context,
                )
                raise _RecoveredPortfolioReconciliationRequiredError(
                    "Recovered LIVE portfolio reconciliation is required"
                )

        return tuple(results)

    async def run(self) -> None:
        """Run trading cycles until stop is requested or the task is cancelled.

        Raises:
            RuntimeError: If the runner is already active.
            Exception: Propagates any trading-cycle failure to the application
                boundary so lifecycle cleanup and failure logging remain
                deterministic.
        """
        if self._running:
            raise RuntimeError("Trading runner is already running")

        self._running = True
        self._stop_event.clear()
        initial_contexts = self._get_cycle_contexts_snapshot()
        _LOGGER.info(
            "Trading runner started: context_count=%d mode=%s candle_limit=%d "
            "cycle_interval_override=%s",
            len(initial_contexts),
            self.trade_mode.value,
            self.candle_limit,
            self.cycle_interval_seconds,
        )

        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name="botragram-runtime-heartbeat",
        )

        try:
            consecutive_failures = 0
            autonomous_live_recovery_attempts = 0
            await self._notify_started()

            while not self._stop_event.is_set():
                active = await self.runtime_control.wait_until_active(
                    stop_event=self._stop_event,
                )

                if not active:
                    break

                contexts: tuple[LiveRuntimePositionContext, ...] = ()
                try:
                    health_snapshot = self._get_autonomous_live_runtime_health_failure()
                    if health_snapshot is not None:
                        health_error = _AutonomousLiveRuntimeHealthUnsafeError(
                            snapshot=health_snapshot,
                        )
                        recovery_allowed = (
                            health_snapshot.status is LiveRuntimeHealthStatus.DEGRADED
                            and health_snapshot.authorization_present
                            and health_snapshot.authorization_exact
                        )
                        (
                            recovered,
                            autonomous_live_recovery_attempts,
                        ) = await self._handle_autonomous_live_runtime_failure(
                            error=health_error,
                            attempts_used=autonomous_live_recovery_attempts,
                            recovery_allowed=recovery_allowed,
                        )
                        if not recovered:
                            break

                        consecutive_failures = 0
                        self._global_next_eligible_monotonic = (
                            monotonic() + self._get_global_cadence_seconds()
                        )
                        self._observe_global_discovery(
                            operation="waiting",
                            observation=lambda telemetry: telemetry.wait_until(
                                next_eligible_monotonic=(
                                    self._global_next_eligible_monotonic
                                )
                            ),
                        )
                        await self._wait_for_global_cycle()
                        continue

                    if self._is_global_cycle_executor():
                        results = await self._run_global_cycle()
                        self._global_next_eligible_monotonic = (
                            monotonic() + self._get_global_cadence_seconds()
                        )
                        self._observe_global_discovery(
                            operation="waiting",
                            observation=lambda telemetry: telemetry.wait_until(
                                next_eligible_monotonic=(
                                    self._global_next_eligible_monotonic
                                )
                            ),
                        )
                        await self._notify_cycle_completed(results=results)
                        await self._wait_for_global_cycle()
                        continue

                    contexts = self._get_cycle_contexts_snapshot()
                    if not self._is_multi_context_batch_authorized(
                        contexts=contexts,
                    ):
                        self._pause_unauthorized_multi_context_runtime()
                        continue
                    eligible_contexts = self._get_eligible_contexts(
                        contexts=contexts,
                    )
                    if not eligible_contexts:
                        await self._wait_for_next_eligible_context(
                            contexts=contexts,
                        )
                        continue

                    self._active_batch_context_count = len(eligible_contexts)
                    try:
                        results = await self.run_context_cycles_once(
                            contexts=eligible_contexts,
                        )
                    finally:
                        self._active_batch_context_count = 0
                except _RecoveredPortfolioReconciliationRequiredError:
                    self._pause_unauthorized_multi_context_runtime()
                    continue
                except AutonomousLiveCycleUnsafeError as error:
                    (
                        recovered,
                        autonomous_live_recovery_attempts,
                    ) = await self._handle_autonomous_live_runtime_failure(
                        error=error,
                        attempts_used=autonomous_live_recovery_attempts,
                        recovery_allowed=True,
                    )
                    if not recovered:
                        self._pause_global_discovery_telemetry()
                        break

                    consecutive_failures = 0
                    self._global_next_eligible_monotonic = (
                        monotonic() + self._get_global_cadence_seconds()
                    )
                    self._observe_global_discovery(
                        operation="waiting",
                        observation=lambda telemetry: telemetry.wait_until(
                            next_eligible_monotonic=(
                                self._global_next_eligible_monotonic
                            )
                        ),
                    )
                    await self._wait_for_global_cycle()
                    continue
                except Exception as error:
                    consecutive_failures += 1
                    _LOGGER.warning(
                        "Trading batch failed: context_count=%d error_type=%s "
                        "attempt=%d/%d",
                        len(contexts),
                        type(error).__name__,
                        consecutive_failures,
                        self.maximum_consecutive_failures,
                    )
                    await self._notify_cycle_failed(
                        error=error,
                        consecutive_failures=consecutive_failures,
                    )

                    if consecutive_failures >= self.maximum_consecutive_failures:
                        raise

                    await self._wait_for_delay(
                        delay_seconds=self.failure_retry_delay_seconds,
                    )
                    continue

                consecutive_failures = 0
                self._mark_contexts_completed(contexts=eligible_contexts)
                await self._notify_cycle_completed(results=results)
                await self._wait_for_next_eligible_context(contexts=contexts)
        except asyncio.CancelledError:
            _LOGGER.info("Trading runner cancellation requested")
            raise
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            self._running = False
            await self._notify_stopped()
            _LOGGER.info("Trading runner stopped")

    def stop(self) -> None:
        """Request graceful runtime termination."""
        self._stop_event.set()

    async def _wait_for_delay(self, *, delay_seconds: float) -> None:
        """Wait for a configured delay while remaining immediately stoppable."""
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=delay_seconds,
            )
        except TimeoutError:
            return

    async def _handle_autonomous_live_runtime_failure(
        self,
        *,
        error: Exception,
        attempts_used: int,
        recovery_allowed: bool,
    ) -> tuple[bool, int]:
        """Pause first, then consume at most one shared in-process recovery pass."""
        self.runtime_control.set_position_protection_ready(False)
        self.runtime_control.pause()
        self._pause_global_discovery_telemetry()
        _LOGGER.critical(
            "Autonomous LIVE runtime paused pending recovery: error_type=%s detail=%s",
            type(error).__name__,
            error,
        )
        await self._notify_cycle_failed(
            error=error,
            consecutive_failures=1,
        )

        if not recovery_allowed:
            _LOGGER.critical(
                "Autonomous LIVE runtime health requires restart/operator recovery: "
                "error_type=%s",
                type(error).__name__,
            )
            return False, attempts_used

        if self.autonomous_live_recovery_provider is None:
            return False, attempts_used

        if attempts_used >= self.maximum_autonomous_live_recovery_attempts:
            _LOGGER.critical(
                "Autonomous LIVE in-process recovery budget exhausted: attempts=%d",
                attempts_used,
            )
            return False, attempts_used

        attempt = attempts_used + 1
        recovered = await self._recover_autonomous_live_runtime(
            error=error,
            attempt=attempt,
        )
        return recovered, attempt

    async def _recover_autonomous_live_runtime(
        self,
        *,
        error: Exception,
        attempt: int,
    ) -> bool:
        """Run one bounded autonomous-LIVE recovery pass without candidate replay."""
        if (
            self.trade_mode is not TradeMode.LIVE
            or not self._is_global_cycle_executor()
        ):
            _LOGGER.critical(
                "Autonomous LIVE in-process recovery rejected outside global LIVE mode"
            )
            return False

        provider = self.autonomous_live_recovery_provider
        if provider is None:
            return False

        _LOGGER.warning(
            "Autonomous LIVE in-process recovery started: attempt=%d/%d error_type=%s",
            attempt,
            self.maximum_autonomous_live_recovery_attempts,
            type(error).__name__,
        )
        try:
            recovered = await provider.recover()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Autonomous LIVE in-process recovery raised unexpectedly: attempt=%d",
                attempt,
            )
            return False

        if not recovered:
            _LOGGER.critical(
                "Autonomous LIVE in-process recovery did not restore safe runtime: "
                "attempt=%d",
                attempt,
            )
            return False

        if self.runtime_control.is_paused:
            _LOGGER.critical(
                "Autonomous LIVE recovery reported success but runtime remained "
                "paused: attempt=%d",
                attempt,
            )
            return False

        _LOGGER.warning(
            "Autonomous LIVE in-process recovery completed safely: attempt=%d",
            attempt,
        )
        return True

    async def _heartbeat_loop(self) -> None:
        """Log periodic liveness while the runtime remains active."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.heartbeat_interval_seconds,
                )
            except TimeoutError:
                state = "PAUSED" if self.runtime_control.is_paused else "RUNNING"
                contexts = self.runtime_control.runtime_contexts
                if len(contexts) > 1:
                    _LOGGER.info(
                        "Runtime heartbeat: state=%s context_count=%d "
                        "active_batch_context_count=%d stream=MULTI",
                        state,
                        len(contexts),
                        self._active_batch_context_count,
                    )
                    continue

                _LOGGER.info(
                    "Runtime heartbeat: state=%s symbol=%s strategy=%s stream=%s",
                    state,
                    self.runtime_control.symbol,
                    self.runtime_control.strategy_type.value,
                    "ON" if self.runtime_control.stream_enabled else "OFF",
                )

    async def _notify_started(self) -> None:
        """Notify the optional observer without affecting runtime startup."""
        observer = self.runtime_observer

        if observer is None:
            return

        try:
            await observer.on_started()
        except Exception:
            _LOGGER.exception("Trading runtime startup observer failed")

    async def _notify_cycle_completed(
        self,
        *,
        results: Sequence[TradingResult],
    ) -> None:
        """Notify the optional observer about a successful cycle."""
        observer = self.runtime_observer

        if observer is None:
            return

        try:
            for result in results:
                await observer.on_cycle_completed(result=result)
        except Exception:
            _LOGGER.exception("Trading runtime cycle observer failed")

    async def _notify_cycle_failed(
        self,
        *,
        error: Exception,
        consecutive_failures: int,
    ) -> None:
        """Notify the optional observer about a failed cycle."""
        observer = self.runtime_observer

        if observer is None:
            return

        try:
            await observer.on_cycle_failed(
                error=error,
                consecutive_failures=consecutive_failures,
                maximum_failures=self.maximum_consecutive_failures,
            )
        except Exception:
            _LOGGER.exception("Trading runtime failure observer failed")

    async def _notify_stopped(self) -> None:
        """Notify the optional observer without affecting cleanup."""
        observer = self.runtime_observer

        if observer is None:
            return

        try:
            await observer.on_stopped()
        except Exception:
            _LOGGER.exception("Trading runtime shutdown observer failed")

    def _log_results(
        self,
        *,
        context: LiveRuntimePositionContext | None,
        results: Sequence[TradingResult],
    ) -> None:
        """Log safe summaries without credentials or sensitive payloads."""
        for result in results:
            self._log_result(context=context, result=result)

    def _log_result(
        self,
        *,
        context: LiveRuntimePositionContext | None,
        result: TradingResult,
    ) -> None:
        """Log one safe execution summary without sensitive payloads."""
        reason = self._get_result_reason(result=result)
        symbol = (
            context.symbol if context is not None else result.decision.signal.symbol
        )

        if result.executed:
            order_id = result.order.order_id if result.order is not None else "unknown"
            risk_result = result.decision.risk_result
            risk_amount = risk_result.metrics.risk_amount if risk_result else None
            stop_loss = risk_result.metrics.stop_loss if risk_result else None
            take_profit = risk_result.metrics.take_profit if risk_result else None
            _LOGGER.info(
                "Trading cycle submitted an order: symbol=%s order_id=%s "
                "position=%s reason=%s risk_amount=%s stop_loss=%s take_profit=%s",
                symbol,
                order_id,
                self._get_position_action(
                    signal_type=result.decision.signal.signal_type,
                ),
                reason,
                self._format_optional_decimal(risk_amount),
                self._format_optional_decimal(stop_loss),
                self._format_optional_decimal(take_profit),
            )
            return

        if result.decision.should_execute:
            _LOGGER.info(
                "Trading cycle approved without order submission: symbol=%s "
                "mode=%s reason=%s",
                symbol,
                self.trade_mode.value,
                reason,
            )
            return

        _LOGGER.info(
            "Trading cycle completed without execution: symbol=%s reason=%s",
            symbol,
            reason,
        )

    def _get_single_cycle_context(self) -> LiveRuntimePositionContext:
        """Return the exact singular context or preserve legacy control inputs."""
        contexts = self.runtime_control.runtime_contexts

        if len(contexts) == 1:
            return contexts[0]

        if len(contexts) > 1:
            raise RuntimeError(
                "TradingRunner single-cycle execution requires exactly one "
                "runtime context"
            )

        return LiveRuntimePositionContext(
            symbol=self.runtime_control.symbol,
            interval=self.runtime_control.interval,
            strategy_type=self.runtime_control.strategy_type,
        )

    def _get_cycle_contexts_snapshot(
        self,
    ) -> tuple[LiveRuntimePositionContext, ...]:
        """Return one immutable batch snapshot without selecting a primary.

        Empty canonical context state retains the legacy manually-configured
        single-symbol path. LIVE recovery never resumes an empty portfolio.
        """
        contexts = self.runtime_control.runtime_contexts
        if not contexts:
            contexts = (self._get_single_cycle_context(),)

        self._prune_context_schedule(contexts=contexts)
        return contexts

    def _is_multi_context_batch_authorized(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> bool:
        """Return whether a LIVE multi-context batch remains exactly authorized."""
        if self.trade_mode is not TradeMode.LIVE or len(contexts) <= 1:
            return True

        provider = self.multi_context_activation_precondition_provider
        if provider is None:
            return False

        preconditions = provider.get_multi_context_activation_preconditions(
            runtime_is_stopping=self._stop_event.is_set(),
        )
        return (
            preconditions is not None
            and preconditions.contexts == contexts
            and preconditions.is_eligible
        )

    def _pause_unauthorized_multi_context_runtime(self) -> None:
        """Fail closed after stale recovered LIVE context state is detected."""
        self.runtime_control.clear_live_management_authorization()
        self.runtime_control.pause()
        _LOGGER.critical(
            "LIVE multi-context management paused; recovery reconciliation is required"
        )

    async def _execute_context(
        self,
        *,
        context: LiveRuntimePositionContext,
        live_trading: bool,
        live_management_authorization: (
            LiveRecoveredPositionManagementAuthorization | None
        ),
    ) -> Sequence[TradingResult]:
        """Execute one context with the optional recovered-LIVE capability."""
        if live_management_authorization is None:
            return await self.executor.execute(
                symbol=context.symbol,
                interval=context.interval,
                strategy_type=context.strategy_type,
                candle_limit=self.candle_limit,
                account_balance_override=(
                    None if live_trading else self.paper_account_balance
                ),
                synchronize_position=live_trading,
                submit_order=live_trading,
            )

        return await self.executor.execute(
            symbol=context.symbol,
            interval=context.interval,
            strategy_type=context.strategy_type,
            candle_limit=self.candle_limit,
            account_balance_override=(
                None if live_trading else self.paper_account_balance
            ),
            synchronize_position=live_trading,
            submit_order=live_trading,
            live_management_authorization=live_management_authorization,
        )

    def _is_global_cycle_executor(self) -> bool:
        """Return whether composition selected one market-wide cycle executor."""
        return isinstance(self.executor, GlobalTradingCycleExecutor)

    async def _run_global_cycle(self) -> tuple[TradingResult, ...]:
        """Execute one discovery cycle without selecting a recovered context."""
        executor = self.executor
        if not isinstance(executor, GlobalTradingCycleExecutor):
            raise RuntimeError("Configured executor is not market-wide")

        if self._global_discovery_telemetry is not None:
            self._observe_global_discovery(
                operation="starting",
                observation=self._start_global_discovery_telemetry,
            )

        self.runtime_control.begin_cycle()
        report: GlobalDiscoveryCycleReport | None = None
        try:
            if isinstance(executor, _GlobalDiscoveryCycleReportingExecutor):
                report = await executor.execute_global_report(
                    interval=self.interval,
                    candle_limit=self.candle_limit,
                )
                results = report.results
            else:
                results = tuple(
                    await executor.execute_global(
                        interval=self.interval,
                        candle_limit=self.candle_limit,
                    )
                )
        except AutonomousLiveCycleUnsafeError as error:
            completed_results = error.completed_results
            self._log_results(context=None, results=completed_results)
            if self._global_discovery_telemetry is not None:
                self._observe_global_discovery(
                    operation="failing",
                    observation=lambda current: current.fail_cycle(
                        results=completed_results
                    ),
                )
            raise
        except Exception:
            if self._global_discovery_telemetry is not None:
                self._observe_global_discovery(
                    operation="failing",
                    observation=lambda current: current.fail_cycle(),
                )
            raise
        finally:
            self.runtime_control.end_cycle()

        self._log_results(context=None, results=results)
        if self._global_discovery_telemetry is not None:
            self._observe_global_discovery(
                operation="completing",
                observation=lambda current: self._complete_global_discovery_telemetry(
                    telemetry=current,
                    results=results,
                    report=report,
                ),
            )
        return results

    def _start_global_discovery_telemetry(
        self,
        telemetry: GlobalDiscoveryTelemetry,
    ) -> None:
        """Record and log a local discovery-cycle start."""
        telemetry.begin_cycle(interval=self.interval)
        _LOGGER.info(
            "Global discovery cycle started: interval=%s universe_limit=%s "
            "batch_size=%s top_n=%s",
            self.interval.value,
            telemetry.universe_limit,
            telemetry.batch_size,
            telemetry.top_n,
        )

    @staticmethod
    def _complete_global_discovery_telemetry(
        *,
        telemetry: GlobalDiscoveryTelemetry,
        results: tuple[TradingResult, ...],
        report: GlobalDiscoveryCycleReport | None,
    ) -> None:
        """Record and log completed local telemetry without runtime authority."""
        telemetry.complete_cycle(
            results=results,
            batch=report.batch if report is not None else None,
            signals=report.signals if report is not None else (),
            skipped_capacity=(report.skipped_capacity if report is not None else False),
            stopped_by_capacity=(
                report.stopped_by_capacity if report is not None else False
            ),
        )
        snapshot = telemetry.get_snapshot()
        outcome = (
            snapshot.last_outcome.value
            if snapshot.last_outcome is not None
            else "unknown"
        )
        _LOGGER.info(
            "Global discovery cycle completed: outcome=%s scanned=%s actionable=%s "
            "rank_start=%s rank_end=%s universe_size=%s duration_ms=%s",
            outcome,
            snapshot.scanned_count,
            snapshot.actionable_count,
            snapshot.rank_start,
            snapshot.rank_end,
            snapshot.universe_size,
            snapshot.last_duration_ms,
        )
        for candidate in snapshot.candidates:
            _LOGGER.info(
                "Global discovery candidate processed: symbol=%s side=%s "
                "confidence=%s outcome=%s",
                candidate.symbol,
                candidate.direction.value,
                candidate.confidence,
                candidate.outcome,
            )

    def _get_global_cadence_seconds(self) -> float:
        """Return the established global discovery cadence."""
        return (
            self.cycle_interval_seconds
            if self.cycle_interval_seconds is not None
            else float(self.interval.seconds)
        )

    async def _wait_for_global_cycle(self) -> None:
        """Wait for cadence while waking early on recovered-runtime degradation."""
        while not self._stop_event.is_set():
            delay_seconds = max(
                0.0,
                self._global_next_eligible_monotonic - monotonic(),
            )
            if delay_seconds <= 0:
                return

            if self.runtime_control.is_paused:
                return

            if self._get_autonomous_live_runtime_health_failure() is not None:
                return

            wait_seconds = delay_seconds
            if self._autonomous_live_runtime_health_monitoring_enabled():
                wait_seconds = min(
                    wait_seconds,
                    self.autonomous_live_health_check_interval_seconds,
                )

            await self._wait_for_delay(delay_seconds=wait_seconds)

    def _pause_global_discovery_telemetry(self) -> None:
        """Expose an existing fail-closed pause without changing its semantics."""
        telemetry = self._global_discovery_telemetry
        if telemetry is not None:
            self._observe_global_discovery(
                operation="pausing",
                observation=lambda current: current.pause(),
            )

    def _observe_global_discovery(
        self,
        *,
        operation: str,
        observation: Callable[[GlobalDiscoveryTelemetry], None],
    ) -> None:
        """Run presentation-only telemetry without controlling runtime behavior."""
        telemetry = self._global_discovery_telemetry
        if telemetry is None:
            return

        try:
            observation(telemetry)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Global discovery telemetry failed: operation=%s", operation
            )

    def _autonomous_live_runtime_health_monitoring_enabled(self) -> bool:
        """Return whether local recovered-runtime health should gate fresh entry."""
        return (
            self.trade_mode is TradeMode.LIVE
            and self._is_global_cycle_executor()
            and self.live_runtime_health_provider is not None
            and bool(self.runtime_control.runtime_contexts)
        )

    def _get_autonomous_live_runtime_health_failure(
        self,
    ) -> LiveRuntimeHealthSnapshot | None:
        """Return only health states that must block a fresh autonomous cycle."""
        if not self._autonomous_live_runtime_health_monitoring_enabled():
            return None

        provider = self.live_runtime_health_provider
        if provider is None:
            return None

        snapshot = provider.get_snapshot()
        if snapshot.status in {
            LiveRuntimeHealthStatus.DEGRADED,
            LiveRuntimeHealthStatus.BLOCKED,
        }:
            return snapshot
        return None

    def _get_eligible_contexts(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> tuple[LiveRuntimePositionContext, ...]:
        """Return snapshot contexts due for one sequential batch."""
        current_monotonic = monotonic()
        return tuple(
            context
            for context in contexts
            if self._context_next_eligible_monotonic.get(context, 0.0)
            <= current_monotonic
        )

    def _mark_contexts_completed(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> None:
        """Schedule every fully successful context using its own cadence."""
        completed_at = monotonic()
        for context in contexts:
            self._context_next_eligible_monotonic[context] = (
                completed_at + self._get_context_cadence_seconds(context=context)
            )

    async def _wait_for_next_eligible_context(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> None:
        """Wait once for the earliest context cadence without delaying a batch."""
        deadlines = tuple(
            self._context_next_eligible_monotonic.get(context, 0.0)
            for context in contexts
        )
        next_deadline = min(deadlines, default=monotonic())
        await self._wait_for_delay(
            delay_seconds=max(0.0, next_deadline - monotonic()),
        )

    def _prune_context_schedule(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> None:
        """Drop process-local scheduling state for contexts no longer present."""
        active_contexts = frozenset(contexts)
        stale_contexts = tuple(
            context
            for context in self._context_next_eligible_monotonic
            if context not in active_contexts
        )
        for context in stale_contexts:
            del self._context_next_eligible_monotonic[context]

    def _get_context_cadence_seconds(
        self,
        *,
        context: LiveRuntimePositionContext,
    ) -> float:
        """Return the explicit override or this context's candle cadence."""
        if self.cycle_interval_seconds is not None:
            return self.cycle_interval_seconds

        return float(context.interval.seconds)

    @staticmethod
    def _get_result_reason(*, result: TradingResult) -> str:
        """Return the most specific workflow or strategy reason available."""
        return (
            result.reason
            or result.decision.reason
            or result.decision.signal.reason
            or _RESULT_REASON_UNAVAILABLE
        )

    @staticmethod
    def _get_position_action(*, signal_type: SignalType) -> str:
        """Return the position action represented by a strategy signal."""
        match signal_type:
            case SignalType.BUY:
                return "LONG"
            case SignalType.SELL:
                return "SHORT"
            case SignalType.CLOSE_LONG:
                return "CLOSE_LONG"
            case SignalType.CLOSE_SHORT:
                return "CLOSE_SHORT"
            case SignalType.HOLD:
                return "NONE"

    @staticmethod
    def _format_optional_decimal(value: Decimal | None) -> str:
        """Format optional numeric order context for plain-text logging."""
        return format(value, "f") if value is not None else "N/A"
