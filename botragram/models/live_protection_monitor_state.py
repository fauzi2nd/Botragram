"""
Botragram

Description:
    Immutable state for one active live protection-monitoring context.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from dataclasses import dataclass

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models.live_runtime_position_context import LiveRuntimePositionContext

__all__ = ["LiveProtectionMonitorState"]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class LiveProtectionMonitorState:
    """Expose immutable lifecycle state for one per-symbol monitor."""

    context: LiveRuntimePositionContext
    is_active: bool
    failure_type: str | None = None
