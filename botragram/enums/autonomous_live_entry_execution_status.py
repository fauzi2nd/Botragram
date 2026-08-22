"""Outcomes of one TESTNET autonomous protected-entry execution attempt."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["AutonomousLiveEntryExecutionStatus"]


@unique
class AutonomousLiveEntryExecutionStatus(BaseEnum):
    """Classify autonomous execution without exposing exchange exceptions."""

    EXECUTED_AND_PROTECTED = "executed_and_protected"
    RISK_REJECTED = "risk_rejected"
    MARKET_REFERENCE_REJECTED = "market_reference_rejected"
    AUTHORIZATION_REJECTED = "authorization_rejected"
    EXISTING_POSITION = "existing_position"
    STALE_SIGNAL = "stale_signal"
    SUBMISSION_BLOCKED = "submission_blocked"
    EXCHANGE_REJECTED = "exchange_rejected"
    VENUE_RULE_REJECTED = "venue_rule_rejected"
    EXECUTION_UNSAFE = "execution_unsafe"
