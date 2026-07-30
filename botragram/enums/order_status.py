"""
Botragram

Description:
    Order status enumeration.

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
from enums.base import BaseEnum

__all__ = ["OrderStatus"]


# =============================================================================
# Enums
# =============================================================================
@unique
class OrderStatus(BaseEnum):
    """Supported order statuses."""

    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"

    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
