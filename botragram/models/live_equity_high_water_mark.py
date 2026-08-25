"""Durable high-water mark for one LIVE collateral asset."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

__all__ = ["LiveEquityHighWaterMark"]


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveEquityHighWaterMark:
    """Immutable maximum observed LIVE account equity for one asset."""

    asset: str
    equity: Decimal
    observed_at: datetime
