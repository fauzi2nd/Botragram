"""
Botragram

Description:
    Backward-compatible import for autonomous LIVE entry intents.

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
from botragram.services.execution.autonomous_live_entry_intent_service import (
    AutonomousLiveEntryIntentService,
)

__all__ = ["AutonomousLiveEntryIntentService"]
