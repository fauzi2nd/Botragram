"""
Botragram

Description:
    Notification type enumeration.

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

__all__ = ["NotificationType"]


# =============================================================================
# Enums
# =============================================================================
@unique
class NotificationType(BaseEnum):
    """Supported notification types."""

    SYSTEM = "system"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    SIGNAL = "signal"
    ORDER = "order"
    POSITION = "position"
    TRADE = "trade"

    RISK = "risk"
