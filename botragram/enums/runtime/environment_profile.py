"""
Botragram

Description:
    Credential environment profile enumeration.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.base import BaseEnum

__all__ = [
    "EnvironmentProfile",
]


# =============================================================================
# Environment Profile Enum
# =============================================================================
class EnvironmentProfile(BaseEnum):
    """Supported credential environment profiles."""

    TESTNET = "testnet"
    MAINNET = "mainnet"
