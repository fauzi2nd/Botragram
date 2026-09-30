"""
Botragram

Description:
    Backward-compatible import for protected LIVE Futures entry.

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
from botragram.services.execution.live_futures_entry_service import (
    LiveFuturesEntryService,
)

__all__ = ["LiveFuturesEntryService"]
