"""
Botragram

Description:
    Backward-compatible import path for stored candle resampling.

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
from botragram.services.market.stored_resampled_candle_provider import (
    StoredResampledCandleProvider,
)

__all__ = ["StoredResampledCandleProvider"]
