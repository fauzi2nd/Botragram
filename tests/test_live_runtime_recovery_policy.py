"""Fail-closed regression tests for pure LIVE recovery health gates."""

from __future__ import annotations

from botragram.app.runtime.live_runtime_recovery_policy import LiveRuntimeRecoveryPolicy
from botragram.enums import (
    Interval,
    LiveRuntimeHealthReason,
    LiveRuntimeHealthStatus,
    StrategyType,
)
from botragram.models import LiveRuntimeHealthSnapshot, LiveRuntimePositionContext

__all__: list[str] = []


def _snapshot(
    *,
    status: LiveRuntimeHealthStatus,
    reason: LiveRuntimeHealthReason | None,
    with_position: bool,
    authorization_exact: bool = True,
    runner_paused: bool = True,
) -> LiveRuntimeHealthSnapshot:
    """Build an immutable health snapshot for one safety decision."""
    contexts = (
        (
            LiveRuntimePositionContext(
                symbol="BTCUSDT",
                interval=Interval.M1,
                strategy_type=StrategyType.EMA_CROSS,
            ),
        )
        if with_position
        else ()
    )
    return LiveRuntimeHealthSnapshot(
        status=status,
        reason=reason,
        contexts=contexts,
        affected_contexts=(),
        authorization_present=authorization_exact,
        authorization_exact=authorization_exact,
        runner_paused=runner_paused,
        cycle_in_progress=False,
        stream_states=(),
        monitor_states=(),
    )


def test_unattended_recovery_requires_exact_ownership() -> None:
    """Transient faults are retryable only when exposure has exact ownership."""
    safe = _snapshot(
        status=LiveRuntimeHealthStatus.DEGRADED,
        reason=LiveRuntimeHealthReason.STREAM_STALE,
        with_position=True,
    )
    unsafe = _snapshot(
        status=LiveRuntimeHealthStatus.DEGRADED,
        reason=LiveRuntimeHealthReason.STREAM_STALE,
        with_position=True,
        authorization_exact=False,
    )
    blocked = _snapshot(
        status=LiveRuntimeHealthStatus.BLOCKED,
        reason=LiveRuntimeHealthReason.STREAM_STALE,
        with_position=False,
    )

    assert LiveRuntimeRecoveryPolicy.is_unattended_recovery_safe(safe)
    assert not LiveRuntimeRecoveryPolicy.is_unattended_recovery_safe(unsafe)
    assert not LiveRuntimeRecoveryPolicy.is_unattended_recovery_safe(blocked)


def test_activation_and_convergence_require_matching_pause_state() -> None:
    """A prepared paused runtime activates; only unpaused authority converges."""
    paused = _snapshot(
        status=LiveRuntimeHealthStatus.PAUSED,
        reason=LiveRuntimeHealthReason.RUNNER_PAUSED,
        with_position=True,
    )
    active = _snapshot(
        status=LiveRuntimeHealthStatus.ACTIVE,
        reason=None,
        with_position=True,
        runner_paused=False,
    )

    assert LiveRuntimeRecoveryPolicy.is_ready_to_activate(
        paused,
        runner_paused=True,
        position_protection_ready=True,
    )
    assert not LiveRuntimeRecoveryPolicy.is_ready_to_activate(
        paused,
        runner_paused=True,
        position_protection_ready=False,
    )
    assert LiveRuntimeRecoveryPolicy.has_converged(
        active,
        runner_paused=False,
        position_protection_ready=True,
    )
    assert not LiveRuntimeRecoveryPolicy.has_converged(
        active,
        runner_paused=True,
        position_protection_ready=True,
    )


def test_authoritative_zero_exposure_can_activate_and_converge() -> None:
    """No-position state remains valid only after pause and protection checks."""
    paused_empty = _snapshot(
        status=LiveRuntimeHealthStatus.INACTIVE,
        reason=LiveRuntimeHealthReason.NO_POSITIONS,
        with_position=False,
    )
    active_empty = _snapshot(
        status=LiveRuntimeHealthStatus.INACTIVE,
        reason=LiveRuntimeHealthReason.NO_POSITIONS,
        with_position=False,
        runner_paused=False,
    )

    assert LiveRuntimeRecoveryPolicy.is_ready_to_activate(
        paused_empty,
        runner_paused=True,
        position_protection_ready=True,
    )
    assert LiveRuntimeRecoveryPolicy.has_converged(
        active_empty,
        runner_paused=False,
        position_protection_ready=True,
    )
