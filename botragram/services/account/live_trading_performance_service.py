"""
Botragram

Description:
    Read-only persisted Botragram LIVE trading-performance aggregation.

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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from time import monotonic
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models import ClosedPositionLifecycle
from botragram.repositories import ClosedPositionLifecycleRepository

__all__ = [
    "LiveTradingPerformanceService",
    "TradingPerformanceSnapshot",
]


# =============================================================================
# Constants
# =============================================================================
_DEFAULT_REFRESH_SECONDS: Final[float] = 10.0
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")


# =============================================================================
# Type Aliases
# =============================================================================
type MonotonicClock = Callable[[], float]


# =============================================================================
# Service Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class TradingPerformanceSnapshot:
    """Immutable aggregate of persisted Botragram LIVE exit fills."""

    closed_trade_count: int
    win_count: int
    loss_count: int
    break_even_count: int
    realized_pnl: Decimal
    win_rate_percent: Decimal


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True)
class LiveTradingPerformanceService:
    """Cache and aggregate only Botragram-persisted LIVE exit fills."""

    lifecycle_repository: ClosedPositionLifecycleRepository
    refresh_seconds: float = _DEFAULT_REFRESH_SECONDS
    monotonic_clock: MonotonicClock = monotonic
    _cached_snapshot: TradingPerformanceSnapshot | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _last_refresh_monotonic: float = field(
        default=0.0,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate bounded local-ledger read configuration."""
        if self.refresh_seconds <= 0:
            raise ValueError("LIVE performance refresh interval must be positive")

    async def get_snapshot(self) -> TradingPerformanceSnapshot:
        """Return cached-or-fresh Botragram-only realized performance."""
        now = self.monotonic_clock()
        cached = self._cached_snapshot
        if (
            cached is not None
            and now - self._last_refresh_monotonic < self.refresh_seconds
        ):
            return cached

        lifecycles = await self.lifecycle_repository.get_completed()
        snapshot = self._aggregate(lifecycles=lifecycles)
        self._cached_snapshot = snapshot
        self._last_refresh_monotonic = now
        return snapshot

    @staticmethod
    def _aggregate(
        *,
        lifecycles: Sequence[ClosedPositionLifecycle],
    ) -> TradingPerformanceSnapshot:
        """Aggregate one outcome per completed entry lifecycle using net PnL."""
        outcomes = tuple(lifecycle.net_pnl for lifecycle in lifecycles)
        win_count = sum(outcome > _DECIMAL_ZERO for outcome in outcomes)
        loss_count = sum(outcome < _DECIMAL_ZERO for outcome in outcomes)
        break_even_count = len(outcomes) - win_count - loss_count
        closed_trade_count = len(outcomes)
        decisive_trade_count = win_count + loss_count
        return TradingPerformanceSnapshot(
            closed_trade_count=closed_trade_count,
            win_count=win_count,
            loss_count=loss_count,
            break_even_count=break_even_count,
            realized_pnl=sum(outcomes, start=_DECIMAL_ZERO),
            win_rate_percent=(
                Decimal(win_count) * Decimal("100") / Decimal(decisive_trade_count)
                if decisive_trade_count
                else _DECIMAL_ZERO
            ),
        )
