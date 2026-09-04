"""
Botragram

Description:
    Candlestick data synchronization and gap-filler service.

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
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.repositories import CandleRepository
from botragram.services.market_service import MarketService

__all__ = [
    "CandleSyncService",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_DEFAULT_CATCHUP_DAYS: Final[int] = 1


# =============================================================================
# Service Implementation
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class CandleSyncService:
    """Detect and fill candlestick data gaps against the exchange."""

    market_service: MarketService
    candle_repository: CandleRepository

    async def check_symbol_gap(
        self,
        *,
        symbol: str,
        interval: Interval = Interval.M1,
    ) -> tuple[datetime | None, datetime, int]:
        """Check for time gaps between latest stored candle and current UTC time.

        Args:
            symbol: Trading symbol to inspect.
            interval: Candlestick timeframe.

        Returns:
            A tuple of (last_candle_close_time, now_utc, missing_bar_count).
            If no candles exist for the symbol, last_candle_close_time is None.
        """
        normalized_symbol = symbol.strip().upper()
        now = datetime.now(timezone.utc)
        latest = await self.candle_repository.get_latest(
            symbol=normalized_symbol,
            interval=interval,
            limit=1,
        )

        if not latest:
            return None, now, 0

        last_close = latest[-1].close_time
        gap_seconds = max(0, int((now - last_close).total_seconds()))
        missing_bars = gap_seconds // interval.seconds
        return last_close, now, missing_bars

    async def sync_symbol(
        self,
        *,
        symbol: str,
        interval: Interval = Interval.M1,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        max_candles: int = 10_000,
    ) -> int:
        """Fetch and persist missing candles for a symbol to close data gaps.

        Args:
            symbol: Trading symbol.
            interval: Candlestick timeframe (default: 1m).
            start_time: Explicit start boundary, or None to auto-detect gap.
            end_time: Explicit end boundary, or None for current UTC time.
            max_candles: Upper limit on candles to fetch in one pass.

        Returns:
            Number of candles fetched and persisted.
        """
        normalized_symbol = symbol.strip().upper()
        now = end_time if end_time is not None else datetime.now(timezone.utc)

        if start_time is None:
            last_close, _, _ = await self.check_symbol_gap(
                symbol=normalized_symbol,
                interval=interval,
            )
            if last_close is None:
                start_time = now - timedelta(days=_DEFAULT_CATCHUP_DAYS)
            else:
                start_time = last_close

        if start_time >= now:
            return 0

        gap_seconds = int((now - start_time).total_seconds())
        bars_needed = gap_seconds // interval.seconds
        if bars_needed <= 0:
            return 0

        fetch_limit = min(max_candles, bars_needed + 2)

        try:
            candles = await self.market_service.get_candles(
                symbol=normalized_symbol,
                interval=interval,
                limit=fetch_limit,
                start_time=start_time,
                end_time=now,
                persist=True,
            )
            count = len(candles)
            if count > 0:
                _LOGGER.info(
                    "Synced %d %s candles for %s (%s -> %s)",
                    count,
                    interval.value,
                    normalized_symbol,
                    start_time.isoformat(),
                    now.isoformat(),
                )
            return count
        except Exception as error:
            _LOGGER.warning(
                "Failed to sync candles for %s: %s",
                normalized_symbol,
                error,
            )
            return 0

    async def sync_symbols(
        self,
        *,
        symbols: Sequence[str],
        interval: Interval = Interval.M1,
        start_time: datetime | None = None,
        max_candles_per_symbol: int = 10_000,
        concurrency: int = 3,
    ) -> dict[str, int]:
        """Synchronize multiple symbols concurrently with bounded parallel workers.

        Args:
            symbols: Sequence of trading symbols.
            interval: Candlestick timeframe.
            start_time: Optional explicit start boundary.
            max_candles_per_symbol: Limit per symbol.
            concurrency: Maximum parallel REST requests.

        Returns:
            Dictionary mapping each symbol to the number of synced candles.
        """
        semaphore = asyncio.Semaphore(concurrency)
        results: dict[str, int] = {}

        async def _sync_worker(sym: str) -> None:
            async with semaphore:
                count = await self.sync_symbol(
                    symbol=sym,
                    interval=interval,
                    start_time=start_time,
                    max_candles=max_candles_per_symbol,
                )
                results[sym] = count

        tasks = [asyncio.create_task(_sync_worker(s)) for s in symbols]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return results

    async def run_periodic_sync(
        self,
        *,
        symbols_provider: Callable[[], Awaitable[Sequence[str]]],
        interval: Interval = Interval.M1,
        interval_seconds: int = 300,
        stop_event: asyncio.Event | None = None,
        concurrency: int = 3,
    ) -> None:
        """Run continuous background synchronization across tracked symbols.

        Args:
            symbols_provider: Async callback returning current active symbols.
            interval: Candlestick timeframe to synchronize.
            interval_seconds: Sleep delay between sync rounds.
            stop_event: Optional event to signal graceful termination.
            concurrency: Maximum concurrent sync requests per round.
        """
        _LOGGER.info(
            "Starting continuous candle sync worker: interval=%s cadence=%ds",
            interval.value,
            interval_seconds,
        )

        while stop_event is None or not stop_event.is_set():
            try:
                symbols = await symbols_provider()
                if symbols:
                    summary = await self.sync_symbols(
                        symbols=symbols,
                        interval=interval,
                        concurrency=concurrency,
                    )
                    total_synced = sum(summary.values())
                    _LOGGER.info(
                        "Completed sync round: %d symbols checked, %d candles saved",
                        len(symbols),
                        total_synced,
                    )
            except asyncio.CancelledError:
                break
            except Exception as error:
                _LOGGER.error("Error during periodic candle sync: %s", error)

            if stop_event is not None:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=float(interval_seconds),
                    )
                    break
                except TimeoutError:
                    pass
            else:
                await asyncio.sleep(float(interval_seconds))
