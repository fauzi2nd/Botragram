"""
Botragram

Description:
    Immutable operational health snapshot for recovered LIVE runtime management.

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
from botragram.enums import LiveRuntimeHealthReason, LiveRuntimeHealthStatus
from botragram.models.live_market_stream_state import LiveMarketStreamState
from botragram.models.live_protection_monitor_state import LiveProtectionMonitorState
from botragram.models.live_runtime_position_context import LiveRuntimePositionContext

__all__ = ["LiveRuntimeHealthSnapshot"]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class LiveRuntimeHealthSnapshot:
    """Describe current recovered LIVE runtime health without authorizing action."""

    status: LiveRuntimeHealthStatus
    reason: LiveRuntimeHealthReason | None
    contexts: tuple[LiveRuntimePositionContext, ...]
    affected_contexts: tuple[LiveRuntimePositionContext, ...]
    authorization_present: bool
    authorization_exact: bool
    runner_paused: bool
    cycle_in_progress: bool
    stream_states: tuple[LiveMarketStreamState, ...]
    monitor_states: tuple[LiveProtectionMonitorState, ...]

    def __post_init__(self) -> None:
        """Reject inconsistent operator-visible state combinations."""
        if self.status is LiveRuntimeHealthStatus.INACTIVE:
            if self.contexts or self.reason is not LiveRuntimeHealthReason.NO_POSITIONS:
                raise ValueError("Inactive LIVE runtime health requires no positions")
        elif self.reason is None:
            if self.status is not LiveRuntimeHealthStatus.ACTIVE:
                raise ValueError("Non-active LIVE runtime health requires a reason")
        elif self.status is LiveRuntimeHealthStatus.ACTIVE:
            raise ValueError("Active LIVE runtime health cannot have a reason")
