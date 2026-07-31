"""
Botragram

Description:
    Asset balance model.

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
from decimal import Decimal

__all__ = [
    "Balance",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class Balance:
    """Immutable asset balance."""

    asset: str

    free: Decimal
    locked: Decimal
