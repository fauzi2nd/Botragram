"""Operator-visible autonomous LIVE recovery states."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["AutonomousLiveRecoveryStatus"]


@unique
class AutonomousLiveRecoveryStatus(BaseEnum):
    """Classify known durable autonomous recovery state without control."""

    CLEAR = "clear"
    ENTRY_RECONCILIATION_REQUIRED = "entry_reconciliation_required"
    POST_ENTRY_RECOVERY_REQUIRED = "post_entry_recovery_required"
    MULTIPLE_INCOMPLETE = "multiple_incomplete"
