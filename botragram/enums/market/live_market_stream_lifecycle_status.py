"""
Botragram

Description:
    Lifecycle states for one managed live market stream.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.base import BaseEnum

__all__ = ["LiveMarketStreamLifecycleStatus"]


# =============================================================================
# Enums
# =============================================================================
class LiveMarketStreamLifecycleStatus(BaseEnum):
    """Represent the lifecycle of one owned market stream."""

    NOT_STARTED = "not_started"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"
