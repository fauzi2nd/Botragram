"""Read-only durable autonomous LIVE recovery observability."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from botragram.enums import (
    AutonomousLiveRecoveryReason,
    AutonomousLiveRecoveryStatus,
    SubmissionAttemptStatus,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    AutonomousLiveRecoverySnapshot,
    SubmissionAttempt,
)

__all__ = ["AutonomousLiveRecoveryObservabilityService"]


class _IncompleteAttemptReader(Protocol):
    """Read incomplete durable attempts without mutation or exchange I/O."""

    async def get_incomplete(self) -> Sequence[SubmissionAttempt]:
        """Return durable incomplete attempts in repository order."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousLiveRecoveryObservabilityService:
    """Derive an immutable recovery snapshot from local durable state only."""

    submission_attempt_repository: _IncompleteAttemptReader
    authorization: AutonomousLiveEntryAuthorization | None

    async def get_snapshot(self) -> AutonomousLiveRecoverySnapshot:
        """Return recovery observability without reconciliation or mutation."""
        attempts: Sequence[
            SubmissionAttempt
        ] = await self.submission_attempt_repository.get_incomplete()
        authorized = (
            self.authorization is not None and self.authorization.new_live_entry_allowed
        )
        if not attempts:
            return AutonomousLiveRecoverySnapshot(
                status=AutonomousLiveRecoveryStatus.CLEAR,
                reason=None,
                incomplete_attempt_count=0,
                attempt_status=None,
                client_order_id=None,
                symbol=None,
                autonomous_entry_authorized=authorized,
                new_entry_blocked_by_recovery=False,
            )
        if len(attempts) > 1:
            return AutonomousLiveRecoverySnapshot(
                status=AutonomousLiveRecoveryStatus.MULTIPLE_INCOMPLETE,
                reason=AutonomousLiveRecoveryReason.MULTIPLE_INCOMPLETE_ATTEMPTS,
                incomplete_attempt_count=len(attempts),
                attempt_status=None,
                client_order_id=None,
                symbol=None,
                autonomous_entry_authorized=authorized,
                new_entry_blocked_by_recovery=True,
            )
        attempt = attempts[0]
        status, reason = self._classify_attempt(attempt=attempt)
        return AutonomousLiveRecoverySnapshot(
            status=status,
            reason=reason,
            incomplete_attempt_count=1,
            attempt_status=attempt.status,
            client_order_id=attempt.client_order_id,
            symbol=attempt.symbol,
            autonomous_entry_authorized=authorized,
            new_entry_blocked_by_recovery=True,
        )

    @staticmethod
    def _classify_attempt(
        *,
        attempt: SubmissionAttempt,
    ) -> tuple[AutonomousLiveRecoveryStatus, AutonomousLiveRecoveryReason]:
        """Classify a repository-defined incomplete attempt without inference."""
        if attempt.status is SubmissionAttemptStatus.ACKNOWLEDGED:
            return (
                AutonomousLiveRecoveryStatus.POST_ENTRY_RECOVERY_REQUIRED,
                AutonomousLiveRecoveryReason.ACKNOWLEDGED_UNCOMPLETED,
            )
        if attempt.status is SubmissionAttemptStatus.PREPARED:
            return (
                AutonomousLiveRecoveryStatus.ENTRY_RECONCILIATION_REQUIRED,
                AutonomousLiveRecoveryReason.PREPARED_ATTEMPT,
            )
        if attempt.status is SubmissionAttemptStatus.UNRESOLVED:
            return (
                AutonomousLiveRecoveryStatus.ENTRY_RECONCILIATION_REQUIRED,
                AutonomousLiveRecoveryReason.UNRESOLVED_ATTEMPT,
            )
        raise RuntimeError("Incomplete attempt repository returned a terminal status")
