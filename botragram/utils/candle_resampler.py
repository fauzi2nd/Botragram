"""
Botragram

Description:
    Deterministic OHLCV candlestick resampling utility.

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
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.models import Candle

__all__ = [
    "resample_candles",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")


# =============================================================================
# Private Helper Functions
# =============================================================================
def _get_bucket_open_time(dt: datetime, target_interval: Interval) -> datetime:
    """Return the UTC bucket open time for a given candle timestamp and interval.

    Args:
        dt: Timezone-aware timestamp.
        target_interval: Target timeframe interval.

    Returns:
        Aligned UTC datetime for the bucket start.
    """
    utc_dt = dt.astimezone(timezone.utc)

    if target_interval is Interval.W1:
        days_since_monday = utc_dt.weekday()
        monday = utc_dt - timedelta(days=days_since_monday)
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)

    if target_interval is Interval.MN1:
        return utc_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    epoch_seconds = int(utc_dt.timestamp())
    bucket_seconds = target_interval.seconds
    aligned_epoch = epoch_seconds - (epoch_seconds % bucket_seconds)
    return datetime.fromtimestamp(aligned_epoch, tz=timezone.utc)


def _get_bucket_close_time(
    bucket_open: datetime, target_interval: Interval
) -> datetime:
    """Return the UTC bucket close time for a given bucket open and interval."""
    if target_interval is Interval.MN1:
        return target_interval.next_close_time(close_time=bucket_open)
    return bucket_open + timedelta(seconds=target_interval.seconds)


# =============================================================================
# Public Functions
# =============================================================================
def resample_candles(
    *,
    candles: Sequence[Candle],
    target_interval: Interval,
    closed_only: bool = True,
    min_candles_per_bucket: int = 1,
) -> tuple[Candle, ...]:
    """Resample lower-timeframe candles into higher-timeframe candles.

    Args:
        candles: Chronological or un-ordered sequence of source candles.
        target_interval: Destination timeframe.
        closed_only: When True, excludes any in-progress trailing bucket
            whose close time exceeds the latest source candle's close time.
        min_candles_per_bucket: Minimum number of constituent candles
            required to emit an aggregated candle. Defaults to 1.

    Returns:
        Tuple of aggregated candles ordered from oldest to newest.

    Raises:
        ValueError: If candles contain mixed symbols, mixed source intervals,
            timezone-naive timestamps, invalid minimum coverage, or an
            unsupported / downsampling target interval.
    """
    if not candles:
        return ()

    if min_candles_per_bucket < 1:
        raise ValueError("min_candles_per_bucket must be at least 1")

    expected_symbol = candles[0].symbol
    source_interval = candles[0].interval

    if target_interval.seconds < source_interval.seconds:
        raise ValueError(
            f"Cannot downsample {source_interval.value} to {target_interval.value}"
        )

    if (
        target_interval is not Interval.MN1
        and target_interval.seconds % source_interval.seconds != 0
    ):
        raise ValueError(
            f"Target interval {target_interval.value} ({target_interval.seconds}s) "
            f"is not an integer multiple of source interval "
            f"{source_interval.value} ({source_interval.seconds}s)"
        )

    # Validate uniformity across input candles
    for candle in candles:
        if candle.symbol != expected_symbol:
            raise ValueError(
                f"Mixed symbols in candle sequence: expected {expected_symbol}, "
                f"got {candle.symbol}"
            )
        if candle.interval is not source_interval:
            raise ValueError(
                f"Mixed intervals in candle sequence: expected "
                f"{source_interval.value}, got {candle.interval.value}"
            )
        if candle.open_time.tzinfo is None or candle.open_time.utcoffset() is None:
            raise ValueError("Candle open_time must be timezone-aware")

    # If intervals match exactly, sort and return
    if target_interval is source_interval:
        sorted_candles = tuple(sorted(candles, key=lambda c: c.open_time))
        if closed_only and sorted_candles:
            # All provided source candles are already closed at source_interval
            return sorted_candles
        return sorted_candles

    sorted_source = sorted(candles, key=lambda c: c.open_time)
    latest_source_close = max(c.close_time for c in sorted_source)

    # Group candles into bucket open times
    buckets: defaultdict[datetime, list[Candle]] = defaultdict(list)
    for candle in sorted_source:
        bucket_open = _get_bucket_open_time(candle.open_time, target_interval)
        buckets[bucket_open].append(candle)

    resampled: list[Candle] = []

    for bucket_open in sorted(buckets.keys()):
        bucket_candles = buckets[bucket_open]
        if len(bucket_candles) < min_candles_per_bucket:
            continue

        bucket_close = _get_bucket_close_time(bucket_open, target_interval)

        if closed_only and bucket_close > latest_source_close:
            # Trailing candle is still forming
            continue

        open_price = bucket_candles[0].open_price
        high_price = max(c.high_price for c in bucket_candles)
        low_price = min(c.low_price for c in bucket_candles)
        close_price = bucket_candles[-1].close_price
        volume = sum((c.volume for c in bucket_candles), start=_DECIMAL_ZERO)

        resampled.append(
            Candle(
                symbol=expected_symbol,
                interval=target_interval,
                open_time=bucket_open,
                close_time=bucket_close,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=volume,
            )
        )

    return tuple(resampled)
