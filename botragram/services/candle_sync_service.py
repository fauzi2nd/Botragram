"""
Botragram

Description:
    Backward-compatible import path for candle synchronization service.

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
from botragram.services.market.candle_sync_service import CandleSyncService

__all__ = ["CandleSyncService"]
