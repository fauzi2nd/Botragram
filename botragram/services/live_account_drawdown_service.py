"""Durable account-equity drawdown calculation for LIVE risk checks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from botragram.repositories import LiveEquityHighWaterRepository

__all__ = ["LiveAccountDrawdownService"]


_DECIMAL_ZERO = Decimal("0")


@dataclass(slots=True, kw_only=True)
class LiveAccountDrawdownService:
    """Maintain a durable high-water mark and calculate current drawdown."""

    repository: LiveEquityHighWaterRepository
    asset: str
    _high_water_equity: Decimal | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        """Normalize the configured collateral asset."""
        normalized_asset = self.asset.strip().upper()
        if not normalized_asset:
            raise ValueError("LIVE drawdown asset must not be empty")
        self.asset = normalized_asset

    async def observe(self, *, equity: Decimal) -> Decimal:
        """Record equity when it establishes a new durable high-water mark."""
        self._validate_equity(equity)
        async with self._lock:
            high_water_equity = self._high_water_equity
            if high_water_equity is None:
                existing = await self.repository.get(asset=self.asset)
                high_water_equity = (
                    existing.equity if existing is not None else _DECIMAL_ZERO
                )
            if equity > high_water_equity:
                saved = await self.repository.save_if_greater(
                    asset=self.asset,
                    equity=equity,
                    observed_at=datetime.now(UTC),
                )
                high_water_equity = saved.equity
            self._high_water_equity = high_water_equity
            return high_water_equity

    async def get_current_drawdown_pct(self, *, equity: Decimal) -> Decimal:
        """Return the current fraction below the durable account high-water mark."""
        high_water_equity = await self.observe(equity=equity)
        if high_water_equity <= _DECIMAL_ZERO:
            raise RuntimeError("LIVE account equity high-water mark is invalid")
        return max(
            _DECIMAL_ZERO,
            (high_water_equity - equity) / high_water_equity,
        )

    @staticmethod
    def _validate_equity(equity: Decimal) -> None:
        """Reject non-finite or non-positive observed equity."""
        if not equity.is_finite() or equity <= _DECIMAL_ZERO:
            raise ValueError("LIVE account equity must be finite and positive")
