"""
Botragram

Description:
    Historical candle provider backed by persisted candles and resampling.

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
from datetime import datetime

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.models import Candle
from botragram.repositories import CandleRepository
from botragram.utils.candle_resampler import resample_candles

__all__ = [
    "StoredResampledCandleProvider",
]


# =============================================================================
# Service Implementation
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class StoredResampledCandleProvider:
    """Historical candle provider that loads and resamples stored candles."""

    candle_repository: CandleRepository
    source_interval: Interval = Interval.M1

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        """Provide historical candles for backtesting or analysis.

        Args:
            symbol: Trading pair symbol.
            interval: Requested candle interval.
            limit: Maximum number of candles.
            start_time: Optional inclusive start time.
            end_time: Optional inclusive end time.

        Returns:
            Candles ordered from oldest to newest.

        Raises:
            ValueError: If limit <= 0 or start_time > end_time.
        """
        if limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        if start_time is not None and end_time is not None:
            if start_time > end_time:
                raise ValueError("Candle start time must not be after end time")

            source_candles = await self.candle_repository.get_between(
                symbol=normalized_symbol,
                interval=self.source_interval,
                start_time=start_time,
                end_time=end_time,
            )
            if not source_candles:
                return ()

            if interval is self.source_interval:
                if len(source_candles) > limit:
                    return source_candles[-limit:]
                return source_candles

            resampled = resample_candles(
                candles=source_candles,
                target_interval=interval,
                closed_only=True,
            )
            if len(resampled) > limit:
                return resampled[-limit:]
            return resampled

        # If range is not fully specified, fetch latest
        if interval is self.source_interval:
            return await self.candle_repository.get_latest(
                symbol=normalized_symbol,
                interval=interval,
                limit=limit,
            )

        multiplier = max(1, interval.seconds // self.source_interval.seconds)
        source_limit = (limit + 2) * multiplier

        source_candles = await self.candle_repository.get_latest(
            symbol=normalized_symbol,
            interval=self.source_interval,
            limit=source_limit,
        )
        if not source_candles:
            return ()

        resampled = resample_candles(
            candles=source_candles,
            target_interval=interval,
            closed_only=True,
        )
        if len(resampled) > limit:
            return resampled[-limit:]
        return resampled
