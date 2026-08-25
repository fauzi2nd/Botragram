"""Regression coverage for durable LIVE account drawdown state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.models import LiveEquityHighWaterMark
from botragram.repositories import LiveEquityHighWaterRepository
from botragram.services.live_account_drawdown_service import (
    LiveAccountDrawdownService,
)


@dataclass(slots=True)
class _MemoryHighWaterRepository(LiveEquityHighWaterRepository):
    """Minimal durable-repository double retaining one high-water mark."""

    mark: LiveEquityHighWaterMark | None = None

    async def get(self, *, asset: str) -> LiveEquityHighWaterMark | None:
        """Return the sole stored mark for its normalized asset."""
        if self.mark is None or self.mark.asset != asset.upper():
            return None
        return self.mark

    async def save_if_greater(
        self,
        *,
        asset: str,
        equity: Decimal,
        observed_at: datetime,
    ) -> LiveEquityHighWaterMark:
        """Store the candidate only when it raises the durable high-water mark."""
        existing = await self.get(asset=asset)
        if existing is None or equity > existing.equity:
            self.mark = LiveEquityHighWaterMark(
                asset=asset.upper(),
                equity=equity,
                observed_at=observed_at,
            )
        if self.mark is None:
            raise RuntimeError("Test high-water mark was not persisted")
        return self.mark


@pytest.mark.asyncio
async def test_drawdown_uses_durable_equity_high_water_mark() -> None:
    """Retain a prior peak and expose the actual current drawdown fraction."""
    repository = _MemoryHighWaterRepository(
        mark=LiveEquityHighWaterMark(
            asset="USDT",
            equity=Decimal("125"),
            observed_at=datetime(2026, 8, 25, tzinfo=UTC),
        )
    )
    service = LiveAccountDrawdownService(repository=repository, asset="usdt")

    assert await service.get_current_drawdown_pct(equity=Decimal("100")) == Decimal(
        "0.2"
    )
    assert await service.get_current_drawdown_pct(equity=Decimal("150")) == Decimal("0")
    assert repository.mark is not None
    assert repository.mark.equity == Decimal("150")
