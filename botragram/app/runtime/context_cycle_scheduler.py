"""Process-local cadence scheduling for sequential trading contexts."""

from __future__ import annotations

from dataclasses import dataclass, field

from botragram.models import LiveRuntimePositionContext

__all__ = ["ContextCycleScheduler"]


@dataclass(slots=True)
class ContextCycleScheduler:
    """Track when each immutable runtime context may run again."""

    _next_eligible: dict[LiveRuntimePositionContext, float] = field(
        default_factory=dict[LiveRuntimePositionContext, float],
        init=False,
        repr=False,
    )

    def eligible(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
        now: float,
    ) -> tuple[LiveRuntimePositionContext, ...]:
        """Return due contexts in their original sequential order."""
        return tuple(
            context
            for context in contexts
            if self._next_eligible.get(context, 0.0) <= now
        )

    def mark_completed(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
        completed_at: float,
        cycle_interval_seconds: float | None,
    ) -> None:
        """Schedule successful contexts using the configured candle cadence."""
        for context in contexts:
            cadence = (
                cycle_interval_seconds
                if cycle_interval_seconds is not None
                else float(context.interval.seconds)
            )
            self._next_eligible[context] = completed_at + cadence

    def next_deadline(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
        now: float,
    ) -> float:
        """Return the earliest due time, or now for an empty batch."""
        return min(
            (self._next_eligible.get(context, 0.0) for context in contexts),
            default=now,
        )

    def prune(self, *, contexts: tuple[LiveRuntimePositionContext, ...]) -> None:
        """Forget contexts no longer owned by the runtime."""
        active_contexts = frozenset(contexts)
        for context in tuple(self._next_eligible):
            if context not in active_contexts:
                del self._next_eligible[context]
