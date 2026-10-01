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
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from time import monotonic, time
from typing import Final, Protocol, runtime_checkable

from botragram.app.connectivity import is_transient_connectivity_error
from botragram.app.global_discovery_telemetry import (
    GlobalDiscoverySnapshot,
    GlobalDiscoveryTelemetry,
)
from botragram.app.runtime.autonomous_live_cycle_executor import (
    AutonomousLiveCycleUnsafeError,
    AutonomousLiveTradingCycleExecutor,
    GlobalDiscoveryCycleReport,
)
from botragram.app.runtime.context_cycle_scheduler import ContextCycleScheduler
from botragram.app.runtime.live_runtime_recovery_policy import (
    LiveRuntimeRecoveryPolicy,
)
from botragram.app.runtime.paper_cycle_executors import (
    AutonomousPaperTradingCycleExecutor,
    HumanConfirmedPaperTradingCycleExecutor,
)
from botragram.app.runtime.single_symbol_cycle_executor import (
    SingleSymbolTradingCycleExecutor,
)
from botragram.app.runtime_control import TradingRuntimeControl

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    Interval,
    LiveRuntimeHealthStatus,
    OrderType,
    SignalType,
    StrategyType,
    TradeMode,
)
from botragram.models import (
    DiscoveryScanReport,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimeHealthSnapshot,
    LiveRuntimePositionContext,
    TradingResult,
)
from botragram.services.runtime.multi_context_activation import (
    MultiContextActivationPreconditionProvider,
    MultiContextRunnerActivationPreconditions,
)
from botragram.utils.retry import CappedExponentialBackoff

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
    "calculate_seconds_until_next_candle_close",
]


# =============================================================================
# Constants
# =============================================================================
_DEFAULT_CANDLE_LIMIT: Final[int] = 100
_DEFAULT_PAPER_ACCOUNT_BALANCE: Final[Decimal] = Decimal("10000")
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS: Final[float] = 30.0
_DEFAULT_AUTONOMOUS_LIVE_HEALTH_CHECK_INTERVAL_SECONDS: Final[float] = 1.0
_DEFAULT_CANDLE_CLOSE_BUFFER_SECONDS: Final[float] = 2.0
_RESULT_REASON_UNAVAILABLE: Final[str] = "No reason provided"
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class _RecoveredPortfolioReconciliationRequiredError(RuntimeError):
    """Stop a batch when recovered LIVE portfolio state becomes stale."""


class _AutonomousLiveRuntimeHealthUnsafeError(RuntimeError):
    """Represent one local recovered-runtime health condition fail-closed."""

    def __init__(self, *, snapshot: LiveRuntimeHealthSnapshot) -> None:
        reason = snapshot.reason.value if snapshot.reason is not None else "unknown"
        super().__init__(
            f"Autonomous LIVE runtime health is {snapshot.status.value}: {reason}"
        )
        self.snapshot = snapshot


@dataclass(slots=True, kw_only=True, frozen=True)
class _HealthRecoveryResult:
    """Describe a health-recovery attempt without granting runtime authority."""

    recovered: bool
    attempts_used: int
    wait_for_global_cadence: bool


class _RecoveryConvergence(Enum):
    """Classify a single post-recovery authority check."""

    CONVERGED = "converged"
    RETRY = "retry"
    UNSAFE = "unsafe"


# =============================================================================
# Runtime Contracts
# =============================================================================
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

    async def recover(self, *, activate_runtime: bool = True) -> bool:
        """Prepare safe LIVE state and optionally activate its runtime."""
        ...


class _LiveRuntimeHealthProvider(Protocol):
    """Expose read-only recovered LIVE health without granting authorization."""

    def get_snapshot(self) -> LiveRuntimeHealthSnapshot:
        """Return the current local runtime-health snapshot."""
        ...


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
    unattended_recovery_backoff: CappedExponentialBackoff = field(
        default_factory=CappedExponentialBackoff,
        repr=False,
    )
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
    _context_scheduler: ContextCycleScheduler = field(
        default_factory=ContextCycleScheduler,
        init=False,
        repr=False,
    )
    _active_batch_context_count: int = field(default=0, init=False, repr=False)
    _global_next_eligible_monotonic: float = field(
        default=0.0,
        init=False,
        repr=False,
    )
    _outage_started_monotonic: float | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _outage_reason: str | None = field(default=None, init=False, repr=False)
    _next_recovery_retry_seconds: float = field(default=0.0, init=False, repr=False)
    _outage_known_position_count: int = field(default=0, init=False, repr=False)
    _last_discovery_skipped_capacity: bool = field(
        default=False,
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
        if self._is_paper_discovery_executor():
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

        is_paper_discovery = self._is_paper_discovery_executor()
        if is_paper_discovery:
            self._observe_global_discovery(
                operation="starting",
                observation=self._start_global_discovery_telemetry,
            )

        try:
            results = tuple(
                await self._execute_context(
                    context=context,
                    live_trading=live_trading,
                    live_management_authorization=live_management_authorization,
                )
            )
        except Exception:
            if is_paper_discovery and self._global_discovery_telemetry is not None:
                self._observe_global_discovery(
                    operation="failing",
                    observation=lambda current: current.fail_cycle(),
                )
            raise
        finally:
            self.runtime_control.end_cycle()

        self._log_results(context=context, results=results)
        if is_paper_discovery and self._global_discovery_telemetry is not None:
            scan_report = getattr(self.executor, "last_scan_report", None)
            self._observe_global_discovery(
                operation="completing",
                observation=lambda current: self._complete_global_discovery_telemetry(
                    telemetry=current,
                    results=results,
                    report=None,
                    scan_report=(
                        scan_report
                        if isinstance(scan_report, DiscoveryScanReport)
                        else None
                    ),
                ),
            )

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
                        health_recovery = await self._recover_from_health_failure(
                            snapshot=health_snapshot,
                            attempts_used=autonomous_live_recovery_attempts,
                        )
                        if not health_recovery.recovered:
                            break

                        autonomous_live_recovery_attempts = (
                            health_recovery.attempts_used
                        )
                        consecutive_failures = 0
                        if health_recovery.wait_for_global_cadence:
                            self._schedule_next_global_cycle(
                                delay_seconds=self._get_global_cadence_seconds(),
                            )
                            await self._wait_for_global_cycle()
                        continue

                    if self._is_global_cycle_executor():
                        results = await self._run_global_cycle()
                        self._schedule_next_global_cycle(
                            delay_seconds=self._calculate_next_global_cycle_delay(),
                        )
                        await self._notify_cycle_completed(results=results)
                        await self._wait_for_global_cycle()
                        continue

                    contexts = self._get_cycle_contexts_snapshot()
                    batch = await self._run_due_context_batch(contexts=contexts)
                    if batch is None:
                        continue
                    eligible_contexts, results = batch
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
                    self._schedule_next_global_cycle(
                        delay_seconds=self._calculate_next_global_cycle_delay(),
                    )
                    await self._wait_for_global_cycle()
                    continue
                except Exception as error:
                    if (
                        self._unattended_live_recovery_supported()
                        and is_transient_connectivity_error(error)
                    ):
                        reason = (
                            f"{self.runtime_control.exchange_type.value.lower()}"
                            "_connectivity_unavailable"
                        )
                        recovered = await self._recover_unattended_live_runtime(
                            error=error,
                            reason=reason,
                        )
                        if not recovered:
                            break
                        autonomous_live_recovery_attempts = 0
                        consecutive_failures = 0
                        continue

                    consecutive_failures += 1
                    _LOGGER.warning(
                        "Trading batch failed: context_count=%d error_type=%s "
                        "attempt=%d/%d",
                        len(contexts),
                        type(error).__name__,
                        consecutive_failures,
                        self.maximum_consecutive_failures,
                    )
                    if consecutive_failures >= self.maximum_consecutive_failures:
                        await self._notify_cycle_failed(
                            error=error,
                            consecutive_failures=consecutive_failures,
                        )
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

    async def _recover_from_health_failure(
        self,
        *,
        snapshot: LiveRuntimeHealthSnapshot,
        attempts_used: int,
    ) -> _HealthRecoveryResult:
        """Select unattended or operational recovery for one unsafe health fact."""
        error = _AutonomousLiveRuntimeHealthUnsafeError(snapshot=snapshot)
        if self._is_unattended_health_recovery_safe(snapshot=snapshot):
            if snapshot.reason is None:
                raise RuntimeError("Unattended health recovery reason is missing")
            recovered = await self._recover_unattended_live_runtime(
                error=error,
                reason=snapshot.reason.value,
            )
            return _HealthRecoveryResult(
                recovered=recovered,
                attempts_used=0 if recovered else attempts_used,
                wait_for_global_cadence=False,
            )

        recovery_allowed = (
            snapshot.status is LiveRuntimeHealthStatus.DEGRADED
            and snapshot.authorization_present
            and snapshot.authorization_exact
        )
        (
            recovered,
            new_attempts_used,
        ) = await self._handle_autonomous_live_runtime_failure(
            error=error,
            attempts_used=attempts_used,
            recovery_allowed=recovery_allowed,
        )
        return _HealthRecoveryResult(
            recovered=recovered,
            attempts_used=new_attempts_used,
            wait_for_global_cadence=recovered,
        )

    async def _recover_unattended_live_runtime(
        self,
        *,
        error: Exception,
        reason: str,
    ) -> bool:
        """Stay paused and retry authoritative LIVE recovery until safe or stopped."""
        if not self._unattended_live_recovery_supported():
            return False

        provider = self.autonomous_live_recovery_provider
        health_provider = self.live_runtime_health_provider
        if provider is None or health_provider is None:
            return False

        outage_started = self._begin_unattended_recovery(
            error=error,
            reason=reason,
        )
        retry_attempt = 0
        recovery_attempts = 0
        waiting_for_private_stream = False
        try:
            while not self._stop_event.is_set():
                health_snapshot = health_provider.get_snapshot()
                if self._private_user_data_reseed_pending(
                    snapshot=health_snapshot,
                ):
                    if not waiting_for_private_stream:
                        _LOGGER.warning(
                            "Autonomous LIVE recovery waiting for Futures User "
                            "Data Stream REST reseed: entry_enabled=false"
                        )
                    waiting_for_private_stream = True
                    retry_attempt += 1
                    delay = min(
                        self.unattended_recovery_backoff.get_delay(
                            attempt=retry_attempt,
                        ),
                        self.autonomous_live_health_check_interval_seconds,
                    )
                    self._next_recovery_retry_seconds = delay
                    await self._wait_for_delay(delay_seconds=delay)
                    continue

                if waiting_for_private_stream:
                    waiting_for_private_stream = False
                    retry_attempt = 0

                retry_attempt += 1
                delay = self.unattended_recovery_backoff.get_delay(
                    attempt=retry_attempt,
                )
                self._next_recovery_retry_seconds = delay
                await self._wait_for_delay(delay_seconds=delay)
                if self._stop_event.is_set():
                    return False

                recovery_attempts += 1
                recovered = await self._attempt_unattended_recovery(
                    provider=provider,
                    attempt=recovery_attempts,
                )
                self._remember_current_outage_positions()
                if not recovered:
                    continue

                convergence = self._evaluate_unattended_recovery_convergence(
                    health_provider=health_provider,
                    reason=reason,
                    recovery_attempts=recovery_attempts,
                    outage_started=outage_started,
                )
                if convergence is _RecoveryConvergence.CONVERGED:
                    return True
                if convergence is _RecoveryConvergence.UNSAFE:
                    return False

            return False
        finally:
            self._clear_outage_observability()

    def _begin_unattended_recovery(
        self,
        *,
        error: Exception,
        reason: str,
    ) -> float:
        """Pause LIVE entry and record the start of an observed outage."""
        self._outage_known_position_count = len(self.runtime_control.runtime_contexts)
        self.runtime_control.set_position_protection_ready(False)
        self.runtime_control.pause()
        self._pause_global_discovery_telemetry()
        outage_started = monotonic()
        self._outage_started_monotonic = outage_started
        self._outage_reason = reason
        self._next_recovery_retry_seconds = 0.0
        if reason == "reconciliation_required":
            _LOGGER.info(
                "Autonomous LIVE runtime paused for routine exit reconciliation: "
                "reason=%s error_type=%s entry_enabled=false",
                reason,
                type(error).__name__,
            )
        else:
            _LOGGER.critical(
                "Autonomous LIVE runtime paused for unattended recovery: "
                "reason=%s error_type=%s entry_enabled=false",
                reason,
                type(error).__name__,
            )
        return outage_started

    async def _attempt_unattended_recovery(
        self,
        *,
        provider: _AutonomousLiveRuntimeRecovery,
        attempt: int,
    ) -> bool:
        """Run one dependency recovery pass while preserving cancellation."""
        try:
            return await provider.recover(activate_runtime=False)
        except asyncio.CancelledError:
            raise
        except Exception as recovery_error:
            if not is_transient_connectivity_error(recovery_error):
                _LOGGER.exception(
                    "Autonomous LIVE unattended recovery failed with a "
                    "non-transient error: attempt=%d",
                    attempt,
                )
                raise
            return False

    def _evaluate_unattended_recovery_convergence(
        self,
        *,
        health_provider: _LiveRuntimeHealthProvider,
        reason: str,
        recovery_attempts: int,
        outage_started: float,
    ) -> _RecoveryConvergence:
        """Activate only authoritative recovery and classify the remaining risk."""
        health_snapshot = health_provider.get_snapshot()
        if self._recovery_ready_to_activate(snapshot=health_snapshot):
            try:
                self._activate_recovered_runtime(snapshot=health_snapshot)
            except Exception:
                _LOGGER.exception("Autonomous LIVE recovered runtime activation failed")
                return _RecoveryConvergence.UNSAFE
            health_snapshot = health_provider.get_snapshot()

        if self._authoritative_recovery_converged(snapshot=health_snapshot):
            outage_seconds = max(0.0, monotonic() - outage_started)
            if reason == "reconciliation_required":
                _LOGGER.info(
                    "Autonomous LIVE routine exit reconciliation completed: "
                    "reason=%s attempts=%d duration=%.1fs "
                    "positions_known=%d positions_state=authoritative",
                    reason,
                    recovery_attempts,
                    outage_seconds,
                    len(health_snapshot.contexts),
                )
            else:
                _LOGGER.warning(
                    "Autonomous LIVE unattended recovery restored "
                    "authoritative state: reason=%s attempts=%d "
                    "outage_seconds=%.1f positions_known=%d "
                    "positions_state=authoritative",
                    reason,
                    recovery_attempts,
                    outage_seconds,
                    len(health_snapshot.contexts),
                )
            return _RecoveryConvergence.CONVERGED

        self.runtime_control.set_position_protection_ready(False)
        self.runtime_control.pause()
        if self._private_user_data_reseed_pending(snapshot=health_snapshot):
            return _RecoveryConvergence.RETRY

        health_reason = (
            health_snapshot.reason.value
            if health_snapshot.reason is not None
            else "unknown"
        )
        if LiveRuntimeRecoveryPolicy.is_retryable_reason(health_snapshot.reason):
            _LOGGER.warning(
                "Autonomous LIVE recovery has not converged: "
                "health_status=%s health_reason=%s entry_enabled=false",
                health_snapshot.status.value,
                health_reason,
            )
            return _RecoveryConvergence.RETRY

        _LOGGER.critical(
            "Autonomous LIVE recovery reported REST success but runtime "
            "health is not authoritative: health_status=%s "
            "health_reason=%s entry_enabled=false",
            health_snapshot.status.value,
            health_reason,
        )
        return _RecoveryConvergence.UNSAFE

    def _unattended_live_recovery_supported(self) -> bool:
        """Return whether authoritative autonomous LIVE recovery is available."""
        return (
            self.trade_mode is TradeMode.LIVE
            and self._is_global_cycle_executor()
            and self.autonomous_live_recovery_provider is not None
            and self.live_runtime_health_provider is not None
        )

    @staticmethod
    def _private_user_data_reseed_pending(
        *,
        snapshot: LiveRuntimeHealthSnapshot,
    ) -> bool:
        """Return whether private Futures state still lacks a fresh REST seed."""
        return LiveRuntimeRecoveryPolicy.is_private_stream_reseed_pending(snapshot)

    def _authoritative_recovery_converged(
        self,
        *,
        snapshot: LiveRuntimeHealthSnapshot,
    ) -> bool:
        """Return whether recovered state can safely reopen autonomous entry."""
        return LiveRuntimeRecoveryPolicy.has_converged(
            snapshot,
            runner_paused=self.runtime_control.is_paused,
            position_protection_ready=(
                self.runtime_control.is_position_protection_ready
            ),
        )

    def _recovery_ready_to_activate(
        self,
        *,
        snapshot: LiveRuntimeHealthSnapshot,
    ) -> bool:
        """Return whether paused recovery substrate is complete and authoritative."""
        return LiveRuntimeRecoveryPolicy.is_ready_to_activate(
            snapshot,
            runner_paused=self.runtime_control.is_paused,
            position_protection_ready=(
                self.runtime_control.is_position_protection_ready
            ),
        )

    def _activate_recovered_runtime(
        self,
        *,
        snapshot: LiveRuntimeHealthSnapshot,
    ) -> None:
        """Activate a fully prepared recovered portfolio or authoritative zero."""
        if snapshot.contexts:
            self.runtime_control.resume()
            return
        self.runtime_control.resume_global_cycle()

    def _remember_current_outage_positions(self) -> None:
        """Retain the largest pre-convergence context count for observability."""
        self._outage_known_position_count = max(
            self._outage_known_position_count,
            len(self.runtime_control.runtime_contexts),
        )

    def _clear_outage_observability(self) -> None:
        """Clear process-local outage telemetry after convergence or shutdown."""
        self._outage_started_monotonic = None
        self._outage_reason = None
        self._next_recovery_retry_seconds = 0.0
        self._outage_known_position_count = 0

    @staticmethod
    def _is_unattended_health_recovery_safe(
        *,
        snapshot: LiveRuntimeHealthSnapshot,
    ) -> bool:
        """Allow dependency recovery only with no exposure or exact ownership."""
        return LiveRuntimeRecoveryPolicy.is_unattended_recovery_safe(snapshot)

    async def _handle_autonomous_live_runtime_failure(
        self,
        *,
        error: Exception,
        attempts_used: int,
        recovery_allowed: bool,
    ) -> tuple[bool, int]:
        """Pause first, then retry operational recovery until safe or stopped."""
        self.runtime_control.set_position_protection_ready(False)
        self.runtime_control.pause()
        self._pause_global_discovery_telemetry()
        _LOGGER.critical(
            "Autonomous LIVE runtime paused pending recovery: error_type=%s detail=%s",
            type(error).__name__,
            error,
        )

        if not recovery_allowed:
            _LOGGER.critical(
                "Autonomous LIVE runtime health requires restart/operator recovery: "
                "error_type=%s",
                type(error).__name__,
            )
            await self._notify_cycle_failed(
                error=error,
                consecutive_failures=self.maximum_consecutive_failures,
            )
            return False, attempts_used

        if self.autonomous_live_recovery_provider is None:
            await self._notify_cycle_failed(
                error=error,
                consecutive_failures=self.maximum_consecutive_failures,
            )
            return False, attempts_used

        attempt = attempts_used
        while not self._stop_event.is_set():
            attempt += 1
            recovered = await self._recover_autonomous_live_runtime(
                error=error,
                attempt=attempt,
            )
            if recovered is True:
                return True, attempt
            if recovered is None:
                return False, attempt

            if attempt % self.maximum_autonomous_live_recovery_attempts == 0:
                _LOGGER.warning(
                    "Autonomous LIVE operational recovery remains pending: "
                    "attempts=%d reporting_interval=%d entry_enabled=false",
                    attempt,
                    self.maximum_autonomous_live_recovery_attempts,
                )
            delay = self.unattended_recovery_backoff.get_delay(attempt=attempt)
            _LOGGER.warning(
                "Autonomous LIVE operational recovery retry scheduled: "
                "attempt=%d delay_seconds=%.3f entry_enabled=false",
                attempt + 1,
                delay,
            )
            await self._wait_for_delay(delay_seconds=delay)

        return False, attempt

    async def _recover_autonomous_live_runtime(
        self,
        *,
        error: Exception,
        attempt: int,
    ) -> bool | None:
        """Run one recovery pass and classify retryable versus fatal failure."""
        if (
            self.trade_mode is not TradeMode.LIVE
            or not self._is_global_cycle_executor()
        ):
            _LOGGER.critical(
                "Autonomous LIVE in-process recovery rejected outside global LIVE mode"
            )
            return None

        provider = self.autonomous_live_recovery_provider
        if provider is None:
            return None

        _LOGGER.info(
            "Autonomous LIVE in-process recovery started: attempt=%d error_type=%s",
            attempt,
            type(error).__name__,
        )
        try:
            recovered = await provider.recover()
        except asyncio.CancelledError:
            raise
        except Exception as recovery_error:
            if is_transient_connectivity_error(recovery_error):
                _LOGGER.warning(
                    "Autonomous LIVE in-process recovery dependency unavailable: "
                    "attempt=%d error_type=%s",
                    attempt,
                    type(recovery_error).__name__,
                )
                return False
            _LOGGER.exception(
                "Autonomous LIVE in-process recovery raised a non-recoverable "
                "error: attempt=%d",
                attempt,
            )
            return None

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

        _LOGGER.info(
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
                outage_started = self._outage_started_monotonic
                if outage_started is not None:
                    positions_known = max(
                        self._outage_known_position_count,
                        len(contexts),
                    )
                    positions_state = (
                        "known_non_authoritative"
                        if positions_known
                        else "unknown_during_outage"
                    )
                    _LOGGER.warning(
                        "Runtime heartbeat: state=PAUSED reason=%s "
                        "outage_seconds=%.1f next_retry_seconds=%.3f "
                        "positions_known=%d positions_state=%s "
                        "entry_enabled=false",
                        self._outage_reason,
                        max(0.0, monotonic() - outage_started),
                        self._next_recovery_retry_seconds,
                        positions_known,
                        positions_state,
                    )
                    continue
                if len(contexts) > 1:
                    _LOGGER.info(
                        "Runtime heartbeat: state=%s context_count=%d "
                        "active_batch_context_count=%d stream=MULTI",
                        state,
                        len(contexts),
                        self._active_batch_context_count,
                    )
                    continue

                if self._is_global_cycle_executor():
                    configured_strategy = (
                        self.runtime_control.configured_strategy_type.value
                    )
                    if not contexts:
                        _LOGGER.info(
                            "Runtime heartbeat: state=%s symbol=DISCOVERY "
                            "strategy=%s stream=IDLE",
                            state,
                            configured_strategy,
                        )
                        continue

                    _LOGGER.info(
                        "Runtime heartbeat: state=%s symbol=%s strategy=%s "
                        "discovery_strategy=%s stream=%s",
                        state,
                        self.runtime_control.symbol,
                        self.runtime_control.strategy_type.value,
                        configured_strategy,
                        "ON" if self.runtime_control.stream_enabled else "OFF",
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

    async def _run_due_context_batch(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> (
        tuple[tuple[LiveRuntimePositionContext, ...], tuple[TradingResult, ...]] | None
    ):
        """Run due contexts sequentially after checking LIVE batch authority."""
        if not self._is_multi_context_batch_authorized(contexts=contexts):
            self._pause_unauthorized_multi_context_runtime()
            return None

        eligible_contexts = self._get_eligible_contexts(contexts=contexts)
        if not eligible_contexts:
            await self._wait_for_next_eligible_context(contexts=contexts)
            return None

        self._active_batch_context_count = len(eligible_contexts)
        try:
            results = await self.run_context_cycles_once(contexts=eligible_contexts)
        finally:
            self._active_batch_context_count = 0
        return eligible_contexts, results

    def _is_global_cycle_executor(self) -> bool:
        """Return whether composition selected one market-wide cycle executor."""
        return isinstance(self.executor, GlobalTradingCycleExecutor)

    def _is_paper_discovery_executor(self) -> bool:
        """Return whether this runner executes paper-mode market discovery."""
        return self._global_discovery_telemetry is not None and isinstance(
            self.executor,
            (
                AutonomousPaperTradingCycleExecutor,
                HumanConfirmedPaperTradingCycleExecutor,
            ),
        )

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
        """Record and log the preflight before a possible discovery scan."""
        telemetry.begin_cycle(interval=self.interval)
        if not self._last_discovery_skipped_capacity:
            _LOGGER.info(
                "Global discovery preflight started: interval=%s universe_limit=%s "
                "batch_size=%s top_n=%s",
                self.interval.value,
                telemetry.universe_limit,
                telemetry.batch_size,
                telemetry.top_n,
            )
        else:
            _LOGGER.debug(
                "Global discovery preflight started: interval=%s universe_limit=%s "
                "batch_size=%s top_n=%s (capacity full, probing exit / capacity)",
                self.interval.value,
                telemetry.universe_limit,
                telemetry.batch_size,
                telemetry.top_n,
            )

    def _complete_global_discovery_telemetry(
        self,
        *,
        telemetry: GlobalDiscoveryTelemetry,
        results: tuple[TradingResult, ...],
        report: GlobalDiscoveryCycleReport | None,
        scan_report: DiscoveryScanReport | None = None,
    ) -> None:
        """Record and log completed local telemetry without runtime authority."""
        skipped_capacity = report.skipped_capacity if report is not None else False
        signals = (
            report.signals
            if report is not None
            else scan_report.signals
            if scan_report is not None
            else ()
        )
        scanned_count = scan_report.scanned_count if scan_report is not None else None
        universe_size = scan_report.universe_size if scan_report is not None else None
        rank_start = (
            1 if scan_report is not None and scan_report.scanned_count > 0 else None
        )
        rank_end = (
            scan_report.scanned_count
            if scan_report is not None and scan_report.scanned_count > 0
            else None
        )
        telemetry.complete_cycle(
            results=results,
            batch=report.batch if report is not None else None,
            signals=signals,
            skipped_capacity=skipped_capacity,
            skipped_rate_limit=(
                report.skipped_rate_limit if report is not None else False
            ),
            stopped_by_capacity=(
                report.stopped_by_capacity if report is not None else False
            ),
            scanned_count=scanned_count,
            universe_size=universe_size,
            rank_start=rank_start,
            rank_end=rank_end,
        )
        snapshot = telemetry.get_snapshot()
        outcome = (
            snapshot.last_outcome.value
            if snapshot.last_outcome is not None
            else "unknown"
        )
        if skipped_capacity:
            if not self._last_discovery_skipped_capacity:
                _LOGGER.info(
                    "Global discovery paused: entry capacity reached (maximum open "
                    "positions active). Discovery scanning suspended while positions "
                    "remain open."
                )
            else:
                _LOGGER.debug(
                    "Global discovery cycle completed: outcome=%s (capacity full)",
                    outcome,
                )
            self._last_discovery_skipped_capacity = True
        else:
            if self._last_discovery_skipped_capacity:
                _LOGGER.info("Global discovery resumed: entry capacity available.")
            self._last_discovery_skipped_capacity = False
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

    def calculate_seconds_until_next_candle_close(
        self,
        *,
        wall_time: float | None = None,
        buffer_seconds: float = _DEFAULT_CANDLE_CLOSE_BUFFER_SECONDS,
    ) -> float:
        """Calculate seconds from now until the next candle closes plus buffer."""
        return calculate_seconds_until_next_candle_close(
            interval=self.interval,
            wall_time=wall_time,
            buffer_seconds=buffer_seconds,
        )

    def _get_global_cadence_seconds(self) -> float:
        """Return the established global discovery cadence."""
        return (
            self.cycle_interval_seconds
            if self.cycle_interval_seconds is not None
            else float(self.interval.seconds)
        )

    def calculate_next_global_cycle_delay(self) -> float:
        """Return the delay in seconds until the next global discovery cycle."""
        if (
            self._last_discovery_skipped_capacity
            and self.cycle_interval_seconds is not None
        ):
            return max(
                self.cycle_interval_seconds,
                min(5.0, float(self.interval.seconds)),
            )

        if self.cycle_interval_seconds is not None:
            return self.cycle_interval_seconds

        return self.calculate_seconds_until_next_candle_close()

    def _calculate_next_global_cycle_delay(self) -> float:
        """Return the delay in seconds until the next global discovery cycle."""
        return self.calculate_next_global_cycle_delay()

    def _schedule_next_global_cycle(self, *, delay_seconds: float) -> None:
        """Set the next global deadline and expose it to optional telemetry."""
        self._global_next_eligible_monotonic = monotonic() + delay_seconds
        self._observe_global_discovery(
            operation="waiting",
            observation=lambda telemetry: telemetry.wait_until(
                next_eligible_monotonic=self._global_next_eligible_monotonic
            ),
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
        return self._context_scheduler.eligible(contexts=contexts, now=monotonic())

    def _mark_contexts_completed(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> None:
        """Schedule every fully successful context using its own cadence."""
        self._context_scheduler.mark_completed(
            contexts=contexts,
            completed_at=monotonic(),
            cycle_interval_seconds=self.cycle_interval_seconds,
        )

    async def _wait_for_next_eligible_context(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> None:
        """Wait once for the earliest context cadence without delaying a batch."""
        next_deadline = self._context_scheduler.next_deadline(
            contexts=contexts,
            now=monotonic(),
        )
        await self._wait_for_delay(
            delay_seconds=max(0.0, next_deadline - monotonic()),
        )

    def _prune_context_schedule(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> None:
        """Drop process-local scheduling state for contexts no longer present."""
        self._context_scheduler.prune(contexts=contexts)

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


def calculate_seconds_until_next_candle_close(
    *,
    interval: Interval,
    wall_time: float | None = None,
    buffer_seconds: float = _DEFAULT_CANDLE_CLOSE_BUFFER_SECONDS,
) -> float:
    """Calculate seconds from now until the next candle closes plus buffer."""
    current_wall_time = time() if wall_time is None else wall_time
    interval_seconds = float(interval.seconds)
    if interval_seconds <= 0.0:
        return buffer_seconds
    elapsed_in_candle = current_wall_time % interval_seconds
    delay = (interval_seconds - elapsed_in_candle) + buffer_seconds
    if delay < buffer_seconds:
        delay += interval_seconds
    return delay
