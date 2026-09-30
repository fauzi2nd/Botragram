"""
Botragram

Description:
    Pure safety decisions for autonomous LIVE runtime recovery.

Python:
    3.14+
"""

from __future__ import annotations

from typing import Final

from botragram.enums import LiveRuntimeHealthReason, LiveRuntimeHealthStatus
from botragram.models import LiveRuntimeHealthSnapshot

__all__ = ["LiveRuntimeRecoveryPolicy"]


_RETRYABLE_HEALTH_REASONS: Final[frozenset[LiveRuntimeHealthReason]] = frozenset(
    {
        LiveRuntimeHealthReason.STREAM_MISSING,
        LiveRuntimeHealthReason.STREAM_NOT_READY,
        LiveRuntimeHealthReason.STREAM_FAILED,
        LiveRuntimeHealthReason.STREAM_STALE,
        LiveRuntimeHealthReason.USER_DATA_STREAM_NOT_READY,
        LiveRuntimeHealthReason.MONITOR_MISSING,
        LiveRuntimeHealthReason.MONITOR_UNHEALTHY,
        LiveRuntimeHealthReason.RECONCILIATION_REQUIRED,
    }
)


class LiveRuntimeRecoveryPolicy:
    """Classify immutable health facts without mutating LIVE runtime state."""

    @staticmethod
    def is_retryable_reason(reason: LiveRuntimeHealthReason | None) -> bool:
        """Return whether a transient health reason permits another recovery pass."""
        return reason in _RETRYABLE_HEALTH_REASONS

    @staticmethod
    def is_unattended_recovery_safe(snapshot: LiveRuntimeHealthSnapshot) -> bool:
        """Allow unattended recovery only with zero or exactly owned exposure."""
        return (
            snapshot.status is not LiveRuntimeHealthStatus.BLOCKED
            and LiveRuntimeRecoveryPolicy.is_retryable_reason(snapshot.reason)
            and (
                not snapshot.contexts
                or (snapshot.authorization_present and snapshot.authorization_exact)
            )
        )

    @staticmethod
    def is_private_stream_reseed_pending(snapshot: LiveRuntimeHealthSnapshot) -> bool:
        """Return whether private Futures state still lacks a fresh REST seed."""
        return snapshot.reason is LiveRuntimeHealthReason.USER_DATA_STREAM_NOT_READY

    @staticmethod
    def is_ready_to_activate(
        snapshot: LiveRuntimeHealthSnapshot,
        *,
        runner_paused: bool,
        position_protection_ready: bool,
    ) -> bool:
        """Require a paused, protected and authoritative recovery substrate."""
        if (
            not snapshot.runner_paused
            or not runner_paused
            or not position_protection_ready
        ):
            return False
        if snapshot.contexts:
            return (
                snapshot.status is LiveRuntimeHealthStatus.PAUSED
                and snapshot.reason is LiveRuntimeHealthReason.RUNNER_PAUSED
                and snapshot.authorization_present
                and snapshot.authorization_exact
            )
        return (
            snapshot.status is LiveRuntimeHealthStatus.INACTIVE
            and snapshot.reason is LiveRuntimeHealthReason.NO_POSITIONS
        )

    @staticmethod
    def has_converged(
        snapshot: LiveRuntimeHealthSnapshot,
        *,
        runner_paused: bool,
        position_protection_ready: bool,
    ) -> bool:
        """Require active exact ownership or authoritative empty exposure."""
        if snapshot.runner_paused or runner_paused or not position_protection_ready:
            return False
        if snapshot.status is LiveRuntimeHealthStatus.ACTIVE:
            return (
                snapshot.reason is None
                and snapshot.authorization_present
                and snapshot.authorization_exact
            )
        return (
            snapshot.status is LiveRuntimeHealthStatus.INACTIVE
            and snapshot.reason is LiveRuntimeHealthReason.NO_POSITIONS
            and not snapshot.contexts
        )
