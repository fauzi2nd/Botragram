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
        return [item.value for item in cls]

    @classmethod
    def names(cls) -> list[str]:
        return [item.name for item in cls]

    @classmethod
    def has_value(cls, value: object) -> bool:
        try:
            cls(value)
            return True
        except ValueError, TypeError:
            return False

    @classmethod
    def from_value(cls, value: str) -> Self:
        return cls(value)
