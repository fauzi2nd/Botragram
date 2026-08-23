"""Lifecycle states for durable outbound LIVE entry attempts."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["SubmissionAttemptStatus"]


@unique
class SubmissionAttemptStatus(BaseEnum):
    """Represent the authoritative local state of one LIVE entry attempt."""

    PREPARED = "prepared"
    ACKNOWLEDGED = "acknowledged"
    BLOCKED_BY_EXISTING_POSITION = "blocked_by_existing_position"
    RESOLVED_NO_EXPOSURE = "resolved_no_exposure"
    COMPLETED = "completed"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
