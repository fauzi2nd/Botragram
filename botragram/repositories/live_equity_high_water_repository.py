"""Persistence boundary for LIVE account-equity high-water marks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from botragram.models import LiveEquityHighWaterMark

__all__ = ["LiveEquityHighWaterRepository"]


class LiveEquityHighWaterRepository(ABC):
    """Persist the maximum observed equity independently for each asset."""

    __slots__ = ()

    @abstractmethod
    async def get(self, *, asset: str) -> LiveEquityHighWaterMark | None:
        """Return the existing high-water mark for an asset."""

    @abstractmethod
    async def save_if_greater(
        self,
        *,
        asset: str,
        equity: Decimal,
        observed_at: datetime,
    ) -> LiveEquityHighWaterMark:
        """Persist and return the greater of the existing and supplied equity."""
