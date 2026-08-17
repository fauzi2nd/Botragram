"""
Botragram

Description:
    Human execution-authorization lifecycle enumeration.

Python:
    3.14+
"""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["AuthorizationStatus"]


@unique
class AuthorizationStatus(BaseEnum):
    """Closed lifecycle states for one execution authorization."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
