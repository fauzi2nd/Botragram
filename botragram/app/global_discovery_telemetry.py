"""Read-only local telemetry for autonomous global discovery."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic

from botragram.enums import (
    GlobalDiscoveryCycleOutcome,
    GlobalDiscoveryCycleState,
    Interval,
    SignalType,
)
from botragram.models import DiscoveryUniverseBatch, Signal, TradingResult

__all__ = [
    "GlobalDiscoveryCandidate",
    "GlobalDiscoverySnapshot",
    "GlobalDiscoveryTelemetry",
]


@dataclass(slots=True, kw_only=True, frozen=True)
class GlobalDiscoveryCandidate:
    """One ranked candidate and its local processing outcome."""

    symbol: str
    direction: SignalType
    confidence: Decimal
    outcome: str | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class GlobalDiscoverySnapshot:
    """Immutable presentation snapshot with no execution capability."""

    interval: Interval
    state: GlobalDiscoveryCycleState
    last_outcome: GlobalDiscoveryCycleOutcome | None
    cycle_sequence: int
    cycle_in_progress: bool
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_duration_ms: int | None
    max_symbols: int | None
    universe_limit: int | None
    batch_size: int | None
    top_n: int | None
    universe_size: int | None
    rank_start: int | None
    rank_end: int | None
    scanned_count: int | None
    actionable_count: int | None
    stopped_by_capacity: bool
    candidates: tuple[GlobalDiscoveryCandidate, ...]
    next_eligible_monotonic: float | None


@dataclass(slots=True)
class GlobalDiscoveryTelemetry:
    """Maintain process-local, immutable global discovery snapshots."""

    interval: Interval
    max_symbols: int | None = None
    universe_limit: int | None = None
    batch_size: int | None = None
    top_n: int | None = None
    _snapshot: GlobalDiscoverySnapshot = field(init=False, repr=False)
    _started_monotonic: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Create the initial idle snapshot."""
        self._snapshot = GlobalDiscoverySnapshot(
            interval=self.interval,
            state=GlobalDiscoveryCycleState.IDLE,
            last_outcome=None,
            cycle_sequence=0,
            cycle_in_progress=False,
            last_started_at=None,
            last_finished_at=None,
            last_duration_ms=None,
            max_symbols=self.max_symbols,
            universe_limit=self.universe_limit,
            batch_size=self.batch_size,
            top_n=self.top_n,
            universe_size=None,
            rank_start=None,
            rank_end=None,
            scanned_count=None,
            actionable_count=None,
            stopped_by_capacity=False,
            candidates=(),
            next_eligible_monotonic=None,
        )

    def get_snapshot(self) -> GlobalDiscoverySnapshot:
        """Return an immutable local telemetry snapshot."""
        return self._snapshot

    def get_global_discovery_snapshot(self) -> GlobalDiscoverySnapshot:
        """Satisfy the terminal read-only telemetry presentation contract."""
        return self.get_snapshot()

    def begin_cycle(self, *, interval: Interval) -> None:
        """Record the start of one global discovery cycle."""
        now = datetime.now(UTC)
        self._started_monotonic = monotonic()
        self._snapshot = replace(
            self._snapshot,
            interval=interval,
            state=GlobalDiscoveryCycleState.SCANNING,
            cycle_sequence=self._snapshot.cycle_sequence + 1,
            cycle_in_progress=True,
            last_started_at=now,
            next_eligible_monotonic=None,
        )

    def complete_cycle(
        self,
        *,
        results: tuple[TradingResult, ...],
        batch: DiscoveryUniverseBatch | None = None,
        signals: tuple[Signal, ...] = (),
        skipped_capacity: bool = False,
        stopped_by_capacity: bool = False,
    ) -> None:
        """Record one normal or capacity-skipped local discovery cycle."""
        if skipped_capacity and (
            batch is not None or signals or results or stopped_by_capacity
        ):
            raise ValueError("Capacity-skipped discovery must not contain scan results")

        started = self._started_monotonic
        duration_ms = (
            round((monotonic() - started) * 1_000) if started is not None else None
        )
        candidates = self._build_candidates(
            results=results,
            signals=signals,
            stopped_by_capacity=stopped_by_capacity,
        )
        self._snapshot = replace(
            self._snapshot,
            state=GlobalDiscoveryCycleState.COMPLETED,
            last_outcome=(
                GlobalDiscoveryCycleOutcome.SKIPPED_CAPACITY
                if skipped_capacity
                else GlobalDiscoveryCycleOutcome.COMPLETED
            ),
            cycle_in_progress=False,
            last_finished_at=datetime.now(UTC),
            last_duration_ms=duration_ms,
            universe_size=batch.universe_size if batch is not None else None,
            rank_start=batch.rank_start if batch is not None else None,
            rank_end=batch.rank_end if batch is not None else None,
            scanned_count=(
                len(batch.entries)
                if batch is not None
                else 0
                if skipped_capacity
                else None
            ),
            actionable_count=len(signals) if batch is not None else len(candidates),
            stopped_by_capacity=stopped_by_capacity,
            candidates=candidates,
        )
        self._started_monotonic = None

    def fail_cycle(self, *, results: tuple[TradingResult, ...] = ()) -> None:
        """Record a failed cycle without changing runtime authority."""
        started = self._started_monotonic
        duration_ms = (
            round((monotonic() - started) * 1_000) if started is not None else None
        )
        candidates = self._build_candidates(
            results=results,
            signals=(),
            stopped_by_capacity=False,
        )
        self._snapshot = replace(
            self._snapshot,
            state=GlobalDiscoveryCycleState.COMPLETED,
            last_outcome=GlobalDiscoveryCycleOutcome.FAILED,
            cycle_in_progress=False,
            last_finished_at=datetime.now(UTC),
            last_duration_ms=duration_ms,
            universe_size=None,
            rank_start=None,
            rank_end=None,
            scanned_count=None,
            actionable_count=len(candidates),
            stopped_by_capacity=False,
            candidates=candidates,
        )
        self._started_monotonic = None

    def wait_until(self, *, next_eligible_monotonic: float) -> None:
        """Expose the runner-owned deadline without scheduling work."""
        self._snapshot = replace(
            self._snapshot,
            state=GlobalDiscoveryCycleState.WAITING,
            next_eligible_monotonic=next_eligible_monotonic,
        )

    def pause(self) -> None:
        """Record a fail-closed local pause without changing runtime authority."""
        self._snapshot = replace(
            self._snapshot,
            state=GlobalDiscoveryCycleState.PAUSED,
            cycle_in_progress=False,
            next_eligible_monotonic=None,
        )

    @staticmethod
    def _build_candidates(
        *,
        results: tuple[TradingResult, ...],
        signals: tuple[Signal, ...],
        stopped_by_capacity: bool,
    ) -> tuple[GlobalDiscoveryCandidate, ...]:
        """Correlate discovered signals with processing outcomes by exact symbol."""
        if not signals:
            return tuple(
                GlobalDiscoveryCandidate(
                    symbol=result.decision.signal.symbol,
                    direction=result.decision.signal.signal_type,
                    confidence=result.decision.signal.confidence,
                    outcome=result.reason,
                )
                for result in results
            )

        results_by_symbol = {
            result.decision.signal.symbol: result for result in results
        }
        return tuple(
            GlobalDiscoveryCandidate(
                symbol=signal.symbol,
                direction=signal.signal_type,
                confidence=signal.confidence,
                outcome=(
                    results_by_symbol[signal.symbol].reason
                    if signal.symbol in results_by_symbol
                    else "skipped_capacity"
                    if stopped_by_capacity
                    else None
                ),
            )
            for signal in signals
        )
