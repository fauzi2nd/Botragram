"""
Botragram

Description:
    Position status enumeration.

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
from enum import unique

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.base import BaseEnum

__all__ = ["PositionStatus"]


# =============================================================================
# Enums
# =============================================================================
@unique
class PositionStatus(BaseEnum):
    """Supported position statuses."""

    OPEN = "open"
    CLOSED = "closed"
    LIQUIDATED = "liquidated"
