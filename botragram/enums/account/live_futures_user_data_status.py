"""
Botragram

Description:
    Lifecycle status for the cached Binance Futures User Data Stream.

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

__all__ = [
    "LiveFuturesUserDataStatus",
]


# =============================================================================
# Enums
# =============================================================================
class LiveFuturesUserDataStatus(BaseEnum):
    """Describe the freshness of cached private Futures account data."""

    STARTING = "starting"
    READY = "ready"
    RESYNCING = "resyncing"
    STALE = "stale"
