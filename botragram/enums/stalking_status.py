"""
Botragram

Description:
    Stalking setup status enumeration.

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

__all__ = ["StalkingStatus"]


# =============================================================================
# Enums
# =============================================================================
@unique
class StalkingStatus(BaseEnum):
    """Supported candidate setup stalking statuses."""

    STALKING = "stalking"
    TRIGGERED = "triggered"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
