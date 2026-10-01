"""Outcomes of TESTNET autonomous LIVE entry-intent authorization."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["AutonomousLiveEntryIntentStatus"]


@unique
class AutonomousLiveEntryIntentStatus(BaseEnum):
    """Classify whether a candidate may form a transient entry intent."""

    AUTHORIZED = "authorized"
    RISK_REJECTED = "risk_rejected"
    AUTHORIZATION_REQUIRED = "authorization_required"
