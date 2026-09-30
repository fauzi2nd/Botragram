"""
Botragram

Description:
    Backward-compatible import for the position service.

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
from botragram.services.position.position_service import PositionService

__all__ = ["PositionService"]
