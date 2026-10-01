"""Typed reasons for autonomous LIVE recovery observability."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["AutonomousLiveRecoveryReason"]


@unique
class AutonomousLiveRecoveryReason(BaseEnum):
    """Identify known durable recovery obligations without exchange inference."""

    PREPARED_ATTEMPT = "prepared_attempt"
    UNRESOLVED_ATTEMPT = "unresolved_attempt"
    ACKNOWLEDGED_UNCOMPLETED = "acknowledged_uncompleted"
    MULTIPLE_INCOMPLETE_ATTEMPTS = "multiple_incomplete_attempts"
