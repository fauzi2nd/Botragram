"""Operator portfolio-exit control-plane states."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["OperatorExitStatus"]


@unique
class OperatorExitStatus(BaseEnum):
    """Represent truthful operator-exit and transition progress."""

    IDLE = "idle"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    FLATTENING = "flattening"
    RECOVERY_REQUIRED = "recovery_required"
    RECONCILING = "reconciling"
    SWITCH_PENDING = "switch_pending"
    COMPLETE = "complete"
    FAILED = "failed"
