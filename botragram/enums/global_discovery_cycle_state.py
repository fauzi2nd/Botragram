"""Local autonomous global-discovery lifecycle states."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["GlobalDiscoveryCycleState"]


@unique
class GlobalDiscoveryCycleState(BaseEnum):
    """Describe read-only global-discovery progress."""

    IDLE = "idle"
    WAITING = "waiting"
    SCANNING = "scanning"
    COMPLETED = "completed"
    PAUSED = "paused"
