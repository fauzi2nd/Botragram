"""
Trading Bot

Module:
    models.balance

Description:
    Domain model representing an account balance snapshot.

Python:
    3.14
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from models.asset_balance import AssetBalance
from models.enums import ExchangeType

__all__ = [
    "Balance",
]


@dataclass(slots=True, frozen=True)
class Balance:
    """Represents an account balance snapshot."""

    exchange: ExchangeType

    timestamp: datetime

    assets: tuple[AssetBalance, ...]

    def __post_init__(self) -> None:
        """Validate balance."""

        # ------------------------------------------------------------------
        # Timestamp
        # ------------------------------------------------------------------

        if self.timestamp.tzinfo is None:
            raise ValueError(
                "timestamp must be timezone-aware"
            )

        # ------------------------------------------------------------------
        # Duplicate assets
        # ------------------------------------------------------------------

        names = {asset.asset for asset in self.assets}

        if len(names) != len(self.assets):
            raise ValueError(
                "duplicate assets are not allowed"
            )

    def get(
        self,
        asset: str,
    ) -> AssetBalance | None:
        """Return the balance for the given asset."""

        for balance in self.assets:
            if balance.asset == asset:
                return balance

        return None