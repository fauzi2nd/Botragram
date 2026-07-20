"""
Trading Bot

Module:
    models.asset_balance

Description:
    Domain model representing the balance of a single asset.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = [
    "AssetBalance",
]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class AssetBalance:
    """Represents the balance of a single asset."""

    asset: str

    free: Decimal
    used: Decimal
    total: Decimal

    def __post_init__(self) -> None:
        """Validate asset balance."""

        # ------------------------------------------------------------------
        # Asset
        # ------------------------------------------------------------------

        if not self.asset.strip():
            raise ValueError("asset cannot be empty")

        if " " in self.asset:
            raise ValueError("asset must not contain spaces")

        # ------------------------------------------------------------------
        # Balances
        # ------------------------------------------------------------------

        if self.free < _ZERO:
            raise ValueError("free must be >= 0")

        if self.used < _ZERO:
            raise ValueError("used must be >= 0")

        if self.total < _ZERO:
            raise ValueError("total must be >= 0")

        if self.free + self.used != self.total:
            raise ValueError(
                "free + used must equal total"
            )

    @property
    def available(self) -> Decimal:
        """Return available balance."""

        return self.free