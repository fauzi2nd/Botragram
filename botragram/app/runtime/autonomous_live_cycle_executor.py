"""
Botragram

Description:
    Bounded autonomous LIVE discovery and protected-entry cycle execution.

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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    AutonomousLiveEntryExecutionStatus,
    Interval,
    OrderType,
    StrategyType,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    AutonomousLiveEntryExecutionResult,
    AutonomousLiveEntryIntent,
    AutonomousLiveEntryIntentResult,
    DiscoveryUniverseBatch,
    LiveEntryRiskEvaluation,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePortfolioContext,
    Signal,
    TradingDecision,
    TradingResult,
)

__all__ = [
    "AutonomousLiveCycleUnsafeError",
    "AutonomousLiveTradingCycleExecutor",
    "GlobalDiscoveryCycleReport",
]


_CLOSED_CANDLE_REPLAY_REASON: Final[str] = "closed_candle_opportunity_already_claimed"
_RATE_LIMIT_REASON: Final[str] = "skipped_rate_limit"


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
    skipped_rate_limit: bool = False
    stopped_by_capacity: bool = False

    def __post_init__(self) -> None:
        """Reject contradictory capacity and discovery facts."""
        if self.skipped_capacity and self.skipped_rate_limit:
            raise ValueError("Global discovery cannot have multiple skip reasons")
        if self.skipped_capacity and (
            self.batch is not None
            or self.signals
            or self.results
            or self.stopped_by_capacity
        ):
            raise ValueError("Capacity-skipped discovery cannot contain scan results")
        if self.skipped_rate_limit and self.stopped_by_capacity:
            raise ValueError("Rate-limited discovery cannot stop by capacity")
        if (
            self.skipped_rate_limit
            and self.batch is None
            and (self.signals or self.results)
        ):
            raise ValueError("Rate-limited candidate facts require a ranked batch")
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


class _OpportunityClaimProvider(Protocol):
    """Atomically deny replay of one exact autonomous LIVE closed candle."""

    async def claim(self, *, signal: Signal, interval: Interval) -> bool:
        """Return true only when the closed-candle identity was newly claimed."""
        ...


class _PositionExitProvider(Protocol):
    """Evaluate in-flight positions upon candle close for early exit."""

    async def evaluate_active_positions(
        self,
        *,
        interval: Interval,
        candle_limit: int = ...,
    ) -> Sequence[object]:
        """Evaluate active open positions for early exit."""
        ...


class _StalkingProvider(Protocol):
    """Manage stalking state during autonomous LIVE execution."""

    @property
    def is_paused(self) -> bool:
        """Return whether stalking is currently paused."""
        ...

    def clear_all(self) -> None:
        """Clear all active stalking setups."""
        ...

    def set_paused(self, paused: bool) -> None:
        """Pause or resume stalking operations."""
        ...

    def invalidate_setup(
        self,
        symbol: str,
        reason: str = "Execution guard rejected",
    ) -> object:
        """Explicitly invalidate a stalking setup."""
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


class _RateLimitGovernor(Protocol):
    """Gate optional discovery without delaying safety-critical exchange work."""

    def should_throttle_discovery(self) -> bool:
        """Return whether new discovery must yield to exchange headroom."""
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
    """Execute one authorized network-scoped protected entry."""

    async def execute(
        self,
        *,
        intent: AutonomousLiveEntryIntent,
        authorization: AutonomousLiveEntryAuthorization | None,
    ) -> AutonomousLiveEntryExecutionResult:
        """Return the typed protected-entry execution outcome."""
        ...


class _LiveRuntimePortfolioReconciler(Protocol):
    """Reconcile authoritative LIVE exposure into local management ownership."""

    async def reconcile_context(self) -> LiveRuntimePortfolioContext | None:
        """Return exact managed portfolio or none when reconciliation is unsafe."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousLiveTradingCycleExecutor:
    """Compose ranked network discovery with sequential protected LIVE entry.

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
    opportunity_claim_repository: _OpportunityClaimProvider
    authorization: AutonomousLiveEntryAuthorization
    quote_asset: str
    max_symbols: int
    top_n: int
    max_open_positions: int
    strategy_type: StrategyType
    live_runtime_portfolio_reconciler: _LiveRuntimePortfolioReconciler
    discovery_rate_limit_governor: _RateLimitGovernor | None = None
    position_exit_service: _PositionExitProvider | None = None
    setup_stalking_service: _StalkingProvider | None = None

    def __post_init__(self) -> None:
        """Validate the static network-scoped discovery composition."""
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
            raise ValueError("Autonomous LIVE requires network entry authorization")
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

        if self.position_exit_service is not None and portfolio.contexts:
            exit_decisions = await self.position_exit_service.evaluate_active_positions(
                interval=interval,
                candle_limit=candle_limit,
            )
            if any(getattr(d, "should_exit", False) for d in exit_decisions):
                reconciled = await self._reconcile_live_runtime_portfolio()
                if reconciled is not None:
                    portfolio = reconciled

        if self._portfolio_is_full(portfolio=portfolio):
            if self.setup_stalking_service is not None:
                self.setup_stalking_service.set_paused(True)
            return GlobalDiscoveryCycleReport(skipped_capacity=True)

        if self.setup_stalking_service is not None:
            self.setup_stalking_service.set_paused(False)

        if self._optional_entry_is_rate_limited():
            return GlobalDiscoveryCycleReport(skipped_rate_limit=True)

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
        skipped_rate_limit = False

        for signal in signals:
            if self._portfolio_is_full(portfolio=portfolio):
                if self.setup_stalking_service is not None:
                    self.setup_stalking_service.set_paused(True)
                stopped_by_capacity = True
                break
            if self._optional_entry_is_rate_limited():
                skipped_rate_limit = True
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
                if self.setup_stalking_service is not None:
                    self.setup_stalking_service.invalidate_setup(
                        signal.symbol,
                        reason=f"Intent rejected: {intent_result.status.value}",
                    )
                results.append(
                    self._non_executed_result(
                        decision=decision,
                        reason=intent_result.status.value,
                    )
                )
                continue

            if self._optional_entry_is_rate_limited():
                if self.setup_stalking_service is not None:
                    self.setup_stalking_service.invalidate_setup(
                        signal.symbol,
                        reason=_RATE_LIMIT_REASON,
                    )
                results.append(
                    self._non_executed_result(
                        decision=decision,
                        reason=_RATE_LIMIT_REASON,
                    )
                )
                skipped_rate_limit = True
                break

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
                    if self.setup_stalking_service is not None:
                        self.setup_stalking_service.set_paused(True)
                    stopped_by_capacity = True
                    break
            else:
                if self.setup_stalking_service is not None:
                    self.setup_stalking_service.invalidate_setup(
                        signal.symbol,
                        reason=f"Execution failed: {execution_result.status.value}",
                    )

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
            skipped_rate_limit=skipped_rate_limit,
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

    def _optional_entry_is_rate_limited(self) -> bool:
        """Gate only fresh discovery and entry without delaying reconciliation."""
        governor = self.discovery_rate_limit_governor
        return governor is not None and governor.should_throttle_discovery()

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
        _ = (
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
            reason=_CLOSED_CANDLE_REPLAY_REASON,
        )
        return TradingResult(
            executed=False,
            decision=decision,
            order=None,
            reason=_CLOSED_CANDLE_REPLAY_REASON,
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
