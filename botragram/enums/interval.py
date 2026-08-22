"""
Botragram

Description:
    Candlestick interval timeframes.

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
from calendar import monthrange
from datetime import datetime, timedelta
from enum import unique

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.base import BaseEnum

__all__ = ["Interval"]


# =============================================================================
# Enums
# =============================================================================
@unique
class Interval(BaseEnum):
    """Supported candlestick intervals."""

    # Minutes
    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"

    # Hours
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    H6 = "6h"
    H8 = "8h"
    H12 = "12h"

    # Days
    D1 = "1d"

    # Weeks
    W1 = "1w"

    # Months
    MN1 = "1M"

    @property
    def seconds(self) -> int:
        return {
            Interval.M1: 60,
            Interval.M3: 180,
            Interval.M5: 300,
            Interval.M15: 900,
            Interval.M30: 1800,
            Interval.H1: 3600,
            Interval.H2: 7200,
            Interval.H4: 14400,
            Interval.H6: 21600,
            Interval.H8: 28800,
            Interval.H12: 43200,
            Interval.D1: 86400,
            Interval.W1: 604800,
            Interval.MN1: 2592000,  # pendekatan ±30 hari
        }[self]

    def next_close_time(self, *, close_time: datetime) -> datetime:
        """Return the next eligible close after an aware candle close time.

        Args:
            close_time: Timezone-aware close timestamp of the latest candle.

        Returns:
            The next interval close time in the timestamp's original timezone.

        Raises:
            ValueError: If the close timestamp is timezone-naive.
        """
        if close_time.tzinfo is None or close_time.utcoffset() is None:
            raise ValueError("Candle close_time must be timezone-aware")

        if self is not Interval.MN1:
            return close_time + timedelta(seconds=self.seconds)

        source_last_day = monthrange(close_time.year, close_time.month)[1]
        next_year = close_time.year + (close_time.month // 12)
        next_month = (close_time.month % 12) + 1
        target_last_day = monthrange(next_year, next_month)[1]
        target_day = (
            target_last_day
            if close_time.day == source_last_day
            else min(close_time.day, target_last_day)
        )
        return close_time.replace(
            year=next_year,
            month=next_month,
            day=target_day,
        )
