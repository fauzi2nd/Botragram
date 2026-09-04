"""
Botragram

Description:
    Process-local volume-ranked discovery-universe rotation service.

Python:
    3.14+
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from botragram.models import DiscoveryUniverseBatch, MarketUniverseEntry

__all__ = ["VolumeRankedDiscoveryUniverseService"]


class RankedMarketUniverseProvider(Protocol):
    """Provide a typed market universe already ordered by quote volume."""

    async def get_market_universe(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[MarketUniverseEntry]:
        """Return ranked active symbols for one quote asset."""
        ...


@dataclass(slots=True, kw_only=True)
class VolumeRankedDiscoveryUniverseService:
    """Rotate bounded batches through the volume-ranked active snapshot.

    The active universe is rounded down to the largest multiple of ``batch_size``
    to ensure full batches and avoid trailing partial batches with illiquid
    tail symbols.
    """

    market_service: RankedMarketUniverseProvider
    quote_asset: str
    universe_limit: int
    batch_size: int
    _snapshot: tuple[MarketUniverseEntry, ...] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _next_offset: int = field(default=0, init=False, repr=False)
    _current_batch: DiscoveryUniverseBatch | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Normalize configuration before the first universe read."""
        normalized_quote_asset = self.quote_asset.strip().upper()
        if not normalized_quote_asset:
            raise ValueError("Discovery universe quote asset must not be empty")
        if isinstance(self.universe_limit, bool) or self.universe_limit <= 0:
            raise ValueError("Discovery universe limit must be a positive integer")
        if isinstance(self.batch_size, bool) or self.batch_size <= 0:
            raise ValueError("Discovery batch size must be a positive integer")
        self.quote_asset = normalized_quote_asset

    async def get_current_batch(self) -> DiscoveryUniverseBatch:
        """Return the current unconsumed batch, refreshing only between sweeps."""
        if self._current_batch is not None:
            return self._current_batch

        if self._snapshot is None:
            ranked_entries = await self.market_service.get_market_universe(
                quote_asset=self.quote_asset,
            )
            raw_entries = tuple(ranked_entries)
            if not raw_entries:
                raise RuntimeError("Ranked discovery universe must not be empty")
            full_batch_count = len(raw_entries) // self.batch_size
            usable_count = (
                full_batch_count * self.batch_size
                if full_batch_count > 0
                else len(raw_entries)
            )
            self._snapshot = raw_entries[:usable_count]
            self._next_offset = 0

        snapshot = self._snapshot
        entries = snapshot[self._next_offset : self._next_offset + self.batch_size]
        rank_start = self._next_offset + 1
        batch = DiscoveryUniverseBatch(
            entries=entries,
            universe_size=len(snapshot),
            rank_start=rank_start,
            rank_end=rank_start + len(entries) - 1,
        )
        self._current_batch = batch
        return batch

    def complete_batch(self, *, batch: DiscoveryUniverseBatch) -> None:
        """Advance only the exact batch whose discovery completed normally."""
        if batch is not self._current_batch:
            raise ValueError("Only the current discovery universe batch can complete")

        snapshot = self._snapshot
        if snapshot is None:
            raise RuntimeError("Ranked discovery universe snapshot is unavailable")

        self._current_batch = None
        if batch.rank_end >= len(snapshot):
            self._snapshot = None
            self._next_offset = 0
            return

        self._next_offset = batch.rank_end
