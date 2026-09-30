"""
Botragram

Description:
    Backward-compatible import path for the market service.

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
from botragram.services.market.market_service import MarketService

__all__ = ["MarketService"]
