"""Authoritative reasons for one closed Botragram LIVE position lifecycle."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["ClosedPositionReason"]


@unique
class ClosedPositionReason(BaseEnum):
    """Classify the authoritative exit that closed one position lifecycle."""

    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    STEPPED_STOP = "stepped_stop"
    MANUAL_CLOSE = "manual_close"
    EMERGENCY_CLOSE = "emergency_close"
    RECOVERY_CLOSE = "recovery_close"
    OPERATOR_EXIT = "operator_exit"
