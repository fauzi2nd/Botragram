"""
Botragram

Description:
    Backward-compatible import for autonomous LIVE entry execution.

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
from botragram.services.execution.autonomous_live_entry_execution_service import (
    AutonomousLiveEntryExecutionService,
)

__all__ = ["AutonomousLiveEntryExecutionService"]
