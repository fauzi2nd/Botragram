"""
Botragram

Description:
    Base enum for all project enums.

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
from enum import StrEnum
from typing import Self

__all__ = ["BaseEnum"]


# =============================================================================
# Enums
# =============================================================================
class BaseEnum(StrEnum):
    """Base class for all project enums."""

    @classmethod
    def values(cls) -> list[str]:
        """Return all enum values in declaration order."""
        return [item.value for item in cls]

    @classmethod
    def names(cls) -> list[str]:
        """Return all enum member names in declaration order."""
        return [item.name for item in cls]

    @classmethod
    def has_value(cls, value: object) -> bool:
        """Return whether a string is a valid value for this enum."""
        if not isinstance(value, str):
            return False

        try:
            cls(value)
            return True
        except ValueError, TypeError:
            return False

    @classmethod
    def from_value(cls, value: str) -> Self:
        """Construct an enum member from its string value."""
        return cls(value)
