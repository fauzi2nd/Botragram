"""Local autonomous global-discovery cycle outcomes."""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["GlobalDiscoveryCycleOutcome"]


@unique
class GlobalDiscoveryCycleOutcome(BaseEnum):
    """Describe the last completed global-discovery cycle outcome."""

    COMPLETED = "completed"
    SKIPPED_CAPACITY = "skipped_capacity"
    FAILED = "failed"
