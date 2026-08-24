"""
Botragram

Description:
    Read-only bounded LIVE Futures trading-performance aggregation.

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
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models import Trade

__all__ = [
    "LiveTradingPerformanceService",
    "TradingPerformanceSnapshot",
]


# =============================================================================
# Constants
# =============================================================================
_DEFAULT_TRADE_HISTORY_LIMIT: Final[int] = 1_000
_DEFAULT_REFRESH_SECONDS: Final[float] = 10.0
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")


# =============================================================================
# Dependency Contracts
# =============================================================================
class LiveTradeHistory(Protocol):
    """Read recent account fills without mutating exchange state."""

    async def get_trades(
        self,
        *,
        symbol: str | None,
        limit: int,
    ) -> Sequence[Trade]:
        """Return bounded recent account fills for an optional symbol."""
        ...


type MonotonicClock = Callable[[], float]


# =============================================================================
# Service Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class TradingPerformanceSnapshot:
    """Immutable aggregate of authoritative realized account fills."""

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
    """Cache and aggregate recent realized Futures fills by closing order."""

    exchange_client: LiveTradeHistory
    refresh_seconds: float = _DEFAULT_REFRESH_SECONDS
    trade_history_limit: int = _DEFAULT_TRADE_HISTORY_LIMIT
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
        """Validate bounded account-history polling configuration."""
        if self.refresh_seconds <= 0:
            raise ValueError("LIVE performance refresh interval must be positive")
        if self.trade_history_limit <= 0:
            raise ValueError("LIVE performance trade-history limit must be positive")

    async def get_snapshot(self) -> TradingPerformanceSnapshot:
        """Return cached-or-fresh authoritative LIVE realized performance."""
        now = self.monotonic_clock()
        cached = self._cached_snapshot
        if (
            cached is not None
            and now - self._last_refresh_monotonic < self.refresh_seconds
        ):
            return cached

        trades = await self.exchange_client.get_trades(
            symbol=None,
            limit=self.trade_history_limit,
        )
        snapshot = self._aggregate(trades=trades)
        self._cached_snapshot = snapshot
        self._last_refresh_monotonic = now
        return snapshot

    @staticmethod
    def _aggregate(*, trades: Sequence[Trade]) -> TradingPerformanceSnapshot:
        """Aggregate only fills whose venue supplies realized profit and loss."""
        realized_by_order: dict[str, Decimal] = {}
        for trade in trades:
            realized_pnl = trade.realized_pnl
            if realized_pnl is None:
                continue
            realized_by_order[trade.order_id] = (
                realized_by_order.get(trade.order_id, _DECIMAL_ZERO) + realized_pnl
            )

        outcomes = tuple(realized_by_order.values())
        win_count = sum(outcome > _DECIMAL_ZERO for outcome in outcomes)
        loss_count = sum(outcome < _DECIMAL_ZERO for outcome in outcomes)
        break_even_count = len(outcomes) - win_count - loss_count
        closed_trade_count = len(outcomes)
        return TradingPerformanceSnapshot(
            closed_trade_count=closed_trade_count,
            win_count=win_count,
            loss_count=loss_count,
            break_even_count=break_even_count,
            realized_pnl=sum(outcomes, start=_DECIMAL_ZERO),
            win_rate_percent=(
                Decimal(win_count) * Decimal("100") / Decimal(closed_trade_count)
                if closed_trade_count
                else _DECIMAL_ZERO
            ),
        )
