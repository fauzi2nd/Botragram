"""
Botragram

Description:
    Historical candle loading and backtest orchestration.

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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine.backtest.backtest_engine import BacktestEngine
from botragram.enums import Interval
from botragram.models import BacktestRequest, BacktestResult, Candle

__all__ = [
    "BacktestService",
    "HistoricalCandleProvider",
]


# =============================================================================
# Constants
# =============================================================================
_EXCHANGE_PAGE_LIMIT: Final[int] = 1_000


# =============================================================================
# Protocols
# =============================================================================
class HistoricalCandleProvider(Protocol):
    """Provide bounded historical candle pages."""

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        """Return one historical candle page."""
        ...


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class BacktestService:
    """Load paginated exchange history and execute one backtest."""

    exchange_client: HistoricalCandleProvider
    engine: BacktestEngine

    async def run(self, *, request: BacktestRequest) -> BacktestResult:
        """Download the requested candle range and run the replay engine."""
        candles = await self.load_candles(request=request)
        return await self.engine.run(request=request, candles=candles)

    async def load_candles(
        self,
        *,
        request: BacktestRequest,
    ) -> tuple[Candle, ...]:
        """Download and return historical candles for the given request."""
        return await self._load_candles(request=request)

    async def _load_candles(
        self,
        *,
        request: BacktestRequest,
    ) -> tuple[Candle, ...]:
        """Load an inclusive range using bounded exchange pagination."""
        cursor = request.start_time
        step = timedelta(seconds=request.interval.seconds)
        candles_by_time: dict[datetime, Candle] = {}

        while cursor <= request.end_time:
            remaining = request.max_candles - len(candles_by_time)
            if remaining <= 0:
                raise ValueError(
                    "Historical range exceeds the configured backtest candle limit"
                )

            page_limit = min(_EXCHANGE_PAGE_LIMIT - 2, remaining)
            page_end = min(request.end_time, cursor + step * (page_limit - 1))
            page = await self.exchange_client.get_candles(
                symbol=request.symbol,
                interval=request.interval,
                limit=min(_EXCHANGE_PAGE_LIMIT, page_limit + 2),
                start_time=cursor - step,
                end_time=page_end + step,
            )
            eligible = tuple(
                candle for candle in page if cursor <= candle.open_time <= page_end
            )
            for candle in eligible:
                candles_by_time[candle.open_time] = candle

            if not eligible:
                break

            next_cursor = eligible[-1].open_time + step
            if next_cursor <= cursor:
                raise RuntimeError("Exchange candle pagination did not advance")
            cursor = next_cursor

        ordered_times = sorted(candles_by_time)
        if ordered_times:
            expected_start = request.start_time
            expected_end = request.start_time + step * (
                (request.end_time - request.start_time) // step
            )
            if ordered_times[0] != expected_start or ordered_times[-1] != expected_end:
                raise RuntimeError(
                    "Exchange did not return the complete backtest candle range "
                    f"({ordered_times[0]} to {ordered_times[-1]}, "
                    f"expected {expected_start} to {expected_end})"
                )
            if any(
                current - previous != step
                for previous, current in zip(ordered_times, ordered_times[1:])
            ):
                raise RuntimeError(
                    "Exchange returned a gap in the backtest candle range"
                )

        return tuple(candles_by_time[open_time] for open_time in ordered_times)
