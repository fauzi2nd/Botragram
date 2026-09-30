"""
Botragram

Description:
    Backward-compatible import path for candle retention service.

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
from botragram.services.market.candle_retention_service import CandleRetentionService

__all__ = ["CandleRetentionService"]
