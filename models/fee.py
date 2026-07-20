"""
Trading Bot

Module:
    models.fee

Description:
    Domain model representing a trading fee.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = [
    "Fee",
]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class Fee:
    """Represents a trading fee."""

    asset: str
    cost: Decimal

    def __post_init__(self) -> None:
        """Validate fee."""

        # ------------------------------------------------------------------
        # Asset
        # ------------------------------------------------------------------

        if not self.asset.strip():
            raise ValueError("asset cannot be empty")

        if " " in self.asset:
            raise ValueError("asset must not contain spaces")

        # ------------------------------------------------------------------
        # Cost
        # ------------------------------------------------------------------

        if self.cost < _ZERO:
            raise ValueError("cost must be >= 0")