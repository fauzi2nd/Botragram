"""Immutable read-only autonomous LIVE recovery snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from botragram.enums import (
    AutonomousLiveRecoveryReason,
    AutonomousLiveRecoveryStatus,
    SubmissionAttemptStatus,
)

__all__ = ["AutonomousLiveRecoverySnapshot"]


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousLiveRecoverySnapshot:
    """Describe only durable known recovery state and entry availability."""

    status: AutonomousLiveRecoveryStatus
    reason: AutonomousLiveRecoveryReason | None
    incomplete_attempt_count: int
    attempt_status: SubmissionAttemptStatus | None
    client_order_id: str | None
    symbol: str | None
    autonomous_entry_authorized: bool
    new_entry_blocked_by_recovery: bool

    def __post_init__(self) -> None:
        """Reject ambiguous operator-visible recovery state combinations."""
        if self.incomplete_attempt_count < 0:
            raise ValueError("Incomplete attempt count must not be negative")
        if self.status is AutonomousLiveRecoveryStatus.CLEAR:
            if (
                self.incomplete_attempt_count != 0
                or self.reason is not None
                or self.attempt_status is not None
                or self.client_order_id is not None
                or self.symbol is not None
                or self.new_entry_blocked_by_recovery
            ):
                raise ValueError("Clear recovery snapshot must contain no attempt")
        elif self.status is AutonomousLiveRecoveryStatus.MULTIPLE_INCOMPLETE:
            if self.incomplete_attempt_count < 2 or any(
                value is not None
                for value in (self.attempt_status, self.client_order_id, self.symbol)
            ):
                raise ValueError(
                    "Multiple recovery snapshot must not select an attempt"
                )
        elif (
            self.incomplete_attempt_count != 1
            or self.reason is None
            or self.attempt_status is None
            or self.client_order_id is None
            or self.symbol is None
            or not self.new_entry_blocked_by_recovery
        ):
            raise ValueError("Single incomplete recovery snapshot is inconsistent")
