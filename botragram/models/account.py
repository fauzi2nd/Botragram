"""
Botragram

Description:
    Exchange account model.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models.balance import Balance

__all__ = [
    "Account",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class Account:
    """Immutable exchange account information."""

    balances: tuple[Balance, ...] = ()

    can_trade: bool = False
    can_deposit: bool = False
    can_withdraw: bool = False
