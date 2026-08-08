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
from botragram.engine.backtest_engine import BacktestEngine
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
        candles = await self._load_candles(request=request)
        return await self.engine.run(request=request, candles=candles)

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

            page_limit = min(_EXCHANGE_PAGE_LIMIT, remaining)
            page = await self.exchange_client.get_candles(
                symbol=request.symbol,
                interval=request.interval,
                limit=page_limit,
                start_time=cursor,
                end_time=request.end_time,
            )
            eligible = tuple(
                candle
                for candle in page
                if request.start_time <= candle.open_time <= request.end_time
            )
            for candle in eligible:
                candles_by_time[candle.open_time] = candle

            if not eligible or len(page) < page_limit:
                break

            next_cursor = eligible[-1].open_time + step
            if next_cursor <= cursor:
                raise RuntimeError("Exchange candle pagination did not advance")
            cursor = next_cursor

        return tuple(
            candles_by_time[open_time] for open_time in sorted(candles_by_time)
        )
