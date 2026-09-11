"""
Botragram

Description:
    Position exit evaluation and decision domain models.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import PositionExitAction

__all__ = [
    "PositionExitDecision",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class PositionExitDecision:
    """Immutable decision for in-flight position exit monitoring."""

    action: PositionExitAction
    symbol: str
    reason: str
    confidence: float = 0.0
    trigger_price: Decimal | None = None
    current_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None

    @property
    def should_exit(self) -> bool:
        """Return True when an early exit action is decided."""
        return self.action is not PositionExitAction.HOLD
