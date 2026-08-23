"""Read-only local telemetry for autonomous global discovery."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic

from botragram.enums import GlobalDiscoveryCycleState, Interval, SignalType
from botragram.models import TradingResult

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
    cycle_sequence: int
    cycle_in_progress: bool
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_duration_ms: int | None
    max_symbols: int | None
    top_n: int | None
    scanned_count: int | None
    actionable_count: int | None
    candidates: tuple[GlobalDiscoveryCandidate, ...]
    next_eligible_monotonic: float | None


@dataclass(slots=True)
class GlobalDiscoveryTelemetry:
    """Maintain process-local, immutable global discovery snapshots."""

    interval: Interval
    max_symbols: int | None = None
    top_n: int | None = None
    _snapshot: GlobalDiscoverySnapshot = field(init=False, repr=False)
    _started_monotonic: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Create the initial idle snapshot."""
        self._snapshot = GlobalDiscoverySnapshot(
            interval=self.interval,
            state=GlobalDiscoveryCycleState.IDLE,
            cycle_sequence=0,
            cycle_in_progress=False,
            last_started_at=None,
            last_finished_at=None,
            last_duration_ms=None,
            max_symbols=self.max_symbols,
            top_n=self.top_n,
            scanned_count=None,
            actionable_count=None,
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
            actionable_count=None,
            candidates=(),
            next_eligible_monotonic=None,
        )

    def complete_cycle(self, *, results: tuple[TradingResult, ...]) -> None:
        """Record candidate outcomes from an already completed local cycle."""
        started = self._started_monotonic
        duration_ms = (
            round((monotonic() - started) * 1_000) if started is not None else None
        )
        candidates = tuple(
            GlobalDiscoveryCandidate(
                symbol=result.decision.signal.symbol,
                direction=result.decision.signal.signal_type,
                confidence=result.decision.signal.confidence,
                outcome=result.reason,
            )
            for result in results
        )
        self._snapshot = replace(
            self._snapshot,
            state=GlobalDiscoveryCycleState.COMPLETED,
            cycle_in_progress=False,
            last_finished_at=datetime.now(UTC),
            last_duration_ms=duration_ms,
            actionable_count=len(candidates),
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
