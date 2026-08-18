"""Typed reasons for operator-visible recovered LIVE runtime health."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["LiveRuntimeHealthReason"]


@unique
class LiveRuntimeHealthReason(BaseEnum):
    """Identify a current fail-closed runtime condition without controlling it."""

    NO_POSITIONS = "no_positions"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    AUTHORIZATION_MISSING = "authorization_missing"
    AUTHORIZATION_MISMATCH = "authorization_mismatch"
    STREAM_MISSING = "stream_missing"
    STREAM_NOT_READY = "stream_not_ready"
    STREAM_FAILED = "stream_failed"
    MONITOR_MISSING = "monitor_missing"
    MONITOR_UNHEALTHY = "monitor_unhealthy"
    RUNNER_PAUSED = "runner_paused"
