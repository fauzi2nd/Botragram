"""
Botragram

Description:
    Backward-compatible import for LIVE runtime health service.

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
from botragram.services.runtime.live_runtime_health_service import (
    LiveRuntimeHealthService,
)

__all__ = ["LiveRuntimeHealthService"]
