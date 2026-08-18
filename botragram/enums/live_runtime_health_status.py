"""Operator-visible status for recovered LIVE runtime health."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["LiveRuntimeHealthStatus"]


@unique
class LiveRuntimeHealthStatus(BaseEnum):
    """Classify the complete recovered LIVE runtime without authorizing it."""

    INACTIVE = "inactive"
    ACTIVE = "active"
    PAUSED = "paused"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
