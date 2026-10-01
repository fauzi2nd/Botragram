"""
Botragram

Description:
    Application environment enumeration.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from botragram.enums.base import BaseEnum

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "Environment",
]


# =============================================================================
# Environment Enum
# =============================================================================
class Environment(BaseEnum):
    """Supported application environments."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"
