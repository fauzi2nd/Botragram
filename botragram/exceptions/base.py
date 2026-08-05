"""
Botragram

Description:
    Base exception classes for Botragram.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

__all__ = [
    "BotragramError",
]


class BotragramError(Exception):
    """Base exception for all Botragram-specific errors."""
