"""Lifecycle states for one durable LIVE operator-exit attempt."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["OperatorExitAttemptStatus"]


@unique
class OperatorExitAttemptStatus(BaseEnum):
    """Represent the durable state of one reduce-only operator close."""

    PREPARED = "prepared"
    ACKNOWLEDGED = "acknowledged"
    RECOVERY_REQUIRED = "recovery_required"
    RECONCILING = "reconciling"
    COMPLETED = "completed"
    REJECTED = "rejected"
