"""
Botragram

Description:
    Application notification model.

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
from dataclasses import dataclass
from datetime import datetime

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import NotificationType

__all__ = [
    "Notification",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class Notification:
    """Immutable application notification."""

    title: str
    message: str
    level: NotificationType

    created_at: datetime
