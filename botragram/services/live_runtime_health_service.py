"""
Botragram

Description:
    Read-only aggregation of canonical recovered LIVE runtime health sources.

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
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import (
    LiveFuturesUserDataStatus,
    LiveMarketStreamLifecycleStatus,
    LiveRuntimeHealthReason,
    LiveRuntimeHealthStatus,
)
from botragram.models import (
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveProtectionMonitorState,
    LiveRuntimeHealthSnapshot,
    LiveRuntimePositionContext,
)

__all__ = ["LiveRuntimeHealthService"]


_DEFAULT_STREAM_STALE_AFTER_SECONDS: Final[float] = 30.0


# =============================================================================
# Dependency Contracts
# =============================================================================
class LiveMarketStreamHealthProvider(Protocol):
    """Expose immutable state for each owned LIVE stream."""

    @property
    def stream_states(self) -> tuple[LiveMarketStreamState, ...]:
        """Return all immutable owned stream states."""
        ...


class LiveProtectionMonitorHealthProvider(Protocol):
    """Expose immutable state for each owned LIVE protection monitor."""

    @property
    def monitor_states(self) -> tuple[LiveProtectionMonitorState, ...]:
        """Return all immutable owned protection-monitor states."""
        ...


class LiveFuturesUserDataHealthProvider(Protocol):
    """Expose synchronous private-stream freshness without network polling."""

    @property
    def status(self) -> LiveFuturesUserDataStatus:
        """Return current private-stream freshness."""
        ...


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class LiveRuntimeHealthService:
    """Derive one read-only health snapshot from canonical runtime state."""

    runtime_control: TradingRuntimeControl
    market_stream_service: LiveMarketStreamHealthProvider
    protection_monitoring_service: LiveProtectionMonitorHealthProvider
    live_futures_user_data_service: LiveFuturesUserDataHealthProvider | None = None
    stream_stale_after_seconds: float = _DEFAULT_STREAM_STALE_AFTER_SECONDS
    clock: Callable[[], float] = monotonic

    def __post_init__(self) -> None:
        """Validate stream-freshness timing."""
        if self.stream_stale_after_seconds <= 0:
            raise ValueError("LIVE stream stale threshold must be greater than zero")

    def get_snapshot(self) -> LiveRuntimeHealthSnapshot:
        """Return current complete-portfolio health without side effects."""
        contexts = self.runtime_control.runtime_contexts
        stream_states = self.market_stream_service.stream_states
        monitor_states = self.protection_monitoring_service.monitor_states
        authorization = self.runtime_control.live_management_authorization
        authorization_present = authorization is not None
        authorization_exact = (
            authorization is not None
            and authorization.authorizes_contexts(contexts=contexts)
        )
        runner_paused = self.runtime_control.is_paused
        cycle_in_progress = self.runtime_control.cycle_in_progress

        user_data_service = self.live_futures_user_data_service
        if (
            user_data_service is not None
            and user_data_service.status is not LiveFuturesUserDataStatus.READY
        ):
            return self._snapshot(
                status=LiveRuntimeHealthStatus.DEGRADED,
                reason=LiveRuntimeHealthReason.USER_DATA_STREAM_NOT_READY,
                affected_contexts=contexts,
                contexts=contexts,
                authorization_present=authorization_present,
                authorization_exact=authorization_exact,
                runner_paused=runner_paused,
                cycle_in_progress=cycle_in_progress,
                stream_states=stream_states,
                monitor_states=monitor_states,
            )

        if not contexts:
            return LiveRuntimeHealthSnapshot(
                status=LiveRuntimeHealthStatus.INACTIVE,
                reason=LiveRuntimeHealthReason.NO_POSITIONS,
                affected_contexts=(),
                contexts=contexts,
                authorization_present=authorization_present,
                authorization_exact=authorization_exact,
                runner_paused=runner_paused,
                cycle_in_progress=cycle_in_progress,
                stream_states=stream_states,
                monitor_states=monitor_states,
            )

        reconciliation_context = self.runtime_control.reconciliation_required_context
        if reconciliation_context is not None:
            return self._snapshot(
                status=LiveRuntimeHealthStatus.BLOCKED,
                reason=LiveRuntimeHealthReason.RECONCILIATION_REQUIRED,
                affected_contexts=(reconciliation_context,),
                contexts=contexts,
                authorization_present=authorization_present,
                authorization_exact=authorization_exact,
                runner_paused=runner_paused,
                cycle_in_progress=cycle_in_progress,
                stream_states=stream_states,
                monitor_states=monitor_states,
            )

        stream_failure = self._get_stream_failure(
            contexts=contexts,
            stream_states=stream_states,
        )
        if stream_failure is not None:
            reason, affected_contexts = stream_failure
            return self._snapshot(
                status=LiveRuntimeHealthStatus.DEGRADED,
                reason=reason,
                affected_contexts=affected_contexts,
                contexts=contexts,
                authorization_present=authorization_present,
                authorization_exact=authorization_exact,
                runner_paused=runner_paused,
                cycle_in_progress=cycle_in_progress,
                stream_states=stream_states,
                monitor_states=monitor_states,
            )

        monitor_failure = self._get_monitor_failure(
            contexts=contexts,
            monitor_states=monitor_states,
        )
        if monitor_failure is not None:
            reason, affected_contexts = monitor_failure
            return self._snapshot(
                status=LiveRuntimeHealthStatus.DEGRADED,
                reason=reason,
                affected_contexts=affected_contexts,
                contexts=contexts,
                authorization_present=authorization_present,
                authorization_exact=authorization_exact,
                runner_paused=runner_paused,
                cycle_in_progress=cycle_in_progress,
                stream_states=stream_states,
                monitor_states=monitor_states,
            )

        if not authorization_present:
            return self._snapshot(
                status=LiveRuntimeHealthStatus.BLOCKED,
                reason=LiveRuntimeHealthReason.AUTHORIZATION_MISSING,
                affected_contexts=contexts,
                contexts=contexts,
                authorization_present=authorization_present,
                authorization_exact=authorization_exact,
                runner_paused=runner_paused,
                cycle_in_progress=cycle_in_progress,
                stream_states=stream_states,
                monitor_states=monitor_states,
            )
        if not authorization_exact:
            return self._snapshot(
                status=LiveRuntimeHealthStatus.BLOCKED,
                reason=LiveRuntimeHealthReason.AUTHORIZATION_MISMATCH,
                affected_contexts=contexts,
                contexts=contexts,
                authorization_present=authorization_present,
                authorization_exact=authorization_exact,
                runner_paused=runner_paused,
                cycle_in_progress=cycle_in_progress,
                stream_states=stream_states,
                monitor_states=monitor_states,
            )
        if self.runtime_control.is_paused:
            return self._snapshot(
                status=LiveRuntimeHealthStatus.PAUSED,
                reason=LiveRuntimeHealthReason.RUNNER_PAUSED,
                affected_contexts=(),
                contexts=contexts,
                authorization_present=authorization_present,
                authorization_exact=authorization_exact,
                runner_paused=runner_paused,
                cycle_in_progress=cycle_in_progress,
                stream_states=stream_states,
                monitor_states=monitor_states,
            )

        return self._snapshot(
            status=LiveRuntimeHealthStatus.ACTIVE,
            reason=None,
            affected_contexts=(),
            contexts=contexts,
            authorization_present=authorization_present,
            authorization_exact=authorization_exact,
            runner_paused=runner_paused,
            cycle_in_progress=cycle_in_progress,
            stream_states=stream_states,
            monitor_states=monitor_states,
        )

    @staticmethod
    def _snapshot(
        *,
        status: LiveRuntimeHealthStatus,
        reason: LiveRuntimeHealthReason | None,
        affected_contexts: tuple[LiveRuntimePositionContext, ...],
        contexts: tuple[LiveRuntimePositionContext, ...],
        authorization_present: bool,
        authorization_exact: bool,
        runner_paused: bool,
        cycle_in_progress: bool,
        stream_states: tuple[LiveMarketStreamState, ...],
        monitor_states: tuple[LiveProtectionMonitorState, ...],
    ) -> LiveRuntimeHealthSnapshot:
        """Construct a snapshot after one deterministic health classification."""
        return LiveRuntimeHealthSnapshot(
            status=status,
            reason=reason,
            affected_contexts=affected_contexts,
            contexts=contexts,
            authorization_present=authorization_present,
            authorization_exact=authorization_exact,
            runner_paused=runner_paused,
            cycle_in_progress=cycle_in_progress,
            stream_states=stream_states,
            monitor_states=monitor_states,
        )

    def _get_stream_failure(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
        stream_states: tuple[LiveMarketStreamState, ...],
    ) -> tuple[LiveRuntimeHealthReason, tuple[LiveRuntimePositionContext, ...]] | None:
        """Return the first deterministic stream condition affecting the portfolio."""
        state_by_identity = {
            stream_state.identity: stream_state for stream_state in stream_states
        }
        missing: list[LiveRuntimePositionContext] = []
        failed: list[LiveRuntimePositionContext] = []
        not_ready: list[LiveRuntimePositionContext] = []
        stale: list[LiveRuntimePositionContext] = []
        now = self.clock()

        for context in contexts:
            state = state_by_identity.get(
                LiveMarketStreamIdentity.from_runtime_context(context=context)
            )
            if state is None:
                missing.append(context)
            elif state.lifecycle_status is LiveMarketStreamLifecycleStatus.FAILED:
                failed.append(context)
            elif (
                state.lifecycle_status is not LiveMarketStreamLifecycleStatus.RUNNING
                or not state.first_tick_received
            ):
                not_ready.append(context)
            elif (
                state.last_event_monotonic is None
                or now - state.last_event_monotonic > self.stream_stale_after_seconds
            ):
                stale.append(context)

        if failed:
            return LiveRuntimeHealthReason.STREAM_FAILED, tuple(failed)
        if missing:
            return LiveRuntimeHealthReason.STREAM_MISSING, tuple(missing)
        if not_ready:
            return LiveRuntimeHealthReason.STREAM_NOT_READY, tuple(not_ready)
        if stale:
            return LiveRuntimeHealthReason.STREAM_STALE, tuple(stale)
        return None

    @staticmethod
    def _get_monitor_failure(
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
        monitor_states: tuple[LiveProtectionMonitorState, ...],
    ) -> tuple[LiveRuntimeHealthReason, tuple[LiveRuntimePositionContext, ...]] | None:
        """Return the first deterministic monitor condition affecting the portfolio."""
        state_by_context = {
            monitor_state.context: monitor_state for monitor_state in monitor_states
        }
        missing: list[LiveRuntimePositionContext] = []
        unhealthy: list[LiveRuntimePositionContext] = []

        for context in contexts:
            state = state_by_context.get(context)
            if state is None:
                missing.append(context)
            elif not state.is_active or state.failure_type is not None:
                unhealthy.append(context)

        if missing:
            return LiveRuntimeHealthReason.MONITOR_MISSING, tuple(missing)
        if unhealthy:
            return LiveRuntimeHealthReason.MONITOR_UNHEALTHY, tuple(unhealthy)
        return None
