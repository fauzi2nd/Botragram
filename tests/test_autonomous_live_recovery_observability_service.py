"""Read-only autonomous LIVE recovery observability tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal

from botragram.enums import (
    AutonomousLiveRecoveryReason,
    AutonomousLiveRecoveryStatus,
    Interval,
    OrderSide,
    OrderType,
    SubmissionAttemptStatus,
)
from botragram.models import AutonomousLiveRecoverySnapshot, SubmissionAttempt
from botragram.services import AutonomousLiveRecoveryObservabilityService
from botragram.storage.memory import MemorySubmissionAttemptRepository

_NOW = datetime(2026, 8, 18, tzinfo=timezone.utc)


@dataclass(slots=True)
class _AttemptReader:
    """Record the sole permitted observability read."""

    attempts: tuple[SubmissionAttempt, ...]
    reads: int = 0
    mutations: int = 0

    async def get_incomplete(self) -> tuple[SubmissionAttempt, ...]:
        """Return durable test attempts without exchange or mutation I/O."""
        self.reads += 1
        return self.attempts


def _attempt(
    *, status: SubmissionAttemptStatus, symbol: str = "BTCUSDT"
) -> SubmissionAttempt:
    """Create one durable incomplete attempt."""
    return SubmissionAttempt(
        client_order_id=f"btg-{symbol.lower()}",
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        signal_generated_at=_NOW,
        interval=Interval.M15,
        strategy_type=None,
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_recovery_snapshot_classifies_durable_attempts_without_side_effects() -> None:
    """Expose clear, singular, and multiple states with one repository read."""
    cases = (
        ((), AutonomousLiveRecoveryStatus.CLEAR, None),
        (
            (_attempt(status=SubmissionAttemptStatus.PREPARED),),
            AutonomousLiveRecoveryStatus.ENTRY_RECONCILIATION_REQUIRED,
            AutonomousLiveRecoveryReason.PREPARED_ATTEMPT,
        ),
        (
            (_attempt(status=SubmissionAttemptStatus.UNRESOLVED),),
            AutonomousLiveRecoveryStatus.ENTRY_RECONCILIATION_REQUIRED,
            AutonomousLiveRecoveryReason.UNRESOLVED_ATTEMPT,
        ),
        (
            (_attempt(status=SubmissionAttemptStatus.ACKNOWLEDGED),),
            AutonomousLiveRecoveryStatus.POST_ENTRY_RECOVERY_REQUIRED,
            AutonomousLiveRecoveryReason.ACKNOWLEDGED_UNCOMPLETED,
        ),
        (
            (
                _attempt(status=SubmissionAttemptStatus.PREPARED),
                _attempt(status=SubmissionAttemptStatus.UNRESOLVED, symbol="ETHUSDT"),
            ),
            AutonomousLiveRecoveryStatus.MULTIPLE_INCOMPLETE,
            AutonomousLiveRecoveryReason.MULTIPLE_INCOMPLETE_ATTEMPTS,
        ),
    )
    for attempts, status, reason in cases:
        reader = _AttemptReader(attempts=attempts)
        snapshot = asyncio.run(
            AutonomousLiveRecoveryObservabilityService(
                submission_attempt_repository=reader,
                authorization=None,
            ).get_snapshot()
        )
        assert snapshot.status is status
        assert snapshot.reason is reason
        assert snapshot.incomplete_attempt_count == len(attempts)
        assert snapshot.autonomous_entry_authorized is False
        assert reader.reads == 1
        assert reader.mutations == 0


def test_terminal_attempts_are_not_recovery_blockers() -> None:
    """Only the durable repository's incomplete states can block observability."""
    snapshot = asyncio.run(_get_terminal_attempt_snapshot())
    assert snapshot.status is AutonomousLiveRecoveryStatus.CLEAR


async def _get_terminal_attempt_snapshot() -> AutonomousLiveRecoverySnapshot:
    """Store terminal lifecycle states through the real repository contract."""
    repository = MemorySubmissionAttemptRepository()
    await repository.save(
        attempt=replace(
            _attempt(status=SubmissionAttemptStatus.PREPARED),
            status=SubmissionAttemptStatus.REJECTED,
        )
    )
    await repository.save(
        attempt=replace(
            _attempt(status=SubmissionAttemptStatus.PREPARED, symbol="ETHUSDT"),
            status=SubmissionAttemptStatus.COMPLETED,
        )
    )
    return await AutonomousLiveRecoveryObservabilityService(
        submission_attempt_repository=repository,
        authorization=None,
    ).get_snapshot()
