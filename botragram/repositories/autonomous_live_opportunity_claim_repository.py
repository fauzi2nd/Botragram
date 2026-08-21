"""Durable autonomous LIVE closed-candle replay-denial contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from botragram.enums import Interval
from botragram.models import Signal

__all__ = ["AutonomousLiveOpportunityClaimRepository"]


class AutonomousLiveOpportunityClaimRepository(ABC):
    """Atomically claim autonomous LIVE economic opportunities once."""

    __slots__ = ()

    @abstractmethod
    async def claim(self, *, signal: Signal, interval: Interval) -> bool:
        """Claim one actionable closed-candle identity.

        Returns:
            ``True`` only when this call created the first durable claim.
            ``False`` when the same symbol, interval, strategy, and signal
            generation time was already claimed.
        """
