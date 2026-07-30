"""
Botragram

Description:
    Time and datetime constants.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

__all__ = [
    "ISO_DATETIME_FORMAT",
    "DISPLAY_DATETIME_FORMAT",
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "MINUTES_PER_HOUR",
    "HOURS_PER_DAY",
]

# =============================================================================
# Date & Time Formats
# =============================================================================

ISO_DATETIME_FORMAT: str = "%Y-%m-%dT%H:%M:%S.%fZ"
DISPLAY_DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S UTC"

# =============================================================================
# Time Units
# =============================================================================

SECONDS_PER_MINUTE: int = 60
SECONDS_PER_HOUR: int = 60 * SECONDS_PER_MINUTE
SECONDS_PER_DAY: int = 24 * SECONDS_PER_HOUR

MINUTES_PER_HOUR: int = 60
HOURS_PER_DAY: int = 24
