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
from enum import unique

# =============================================================================
# Local Imports
# =============================================================================
from enums.base import BaseEnum

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
