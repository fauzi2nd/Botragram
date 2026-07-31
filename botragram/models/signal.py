"""
Botragram

Description:
    Trading strategy signal model.

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
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import SignalType

__all__ = [
    "Signal",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class Signal:
    """Immutable trading signal produced by a strategy."""

    symbol: str
    signal_type: SignalType

    price: Decimal
    confidence: Decimal

    strategy_name: str
    generated_at: datetime

    reason: str | None = None
