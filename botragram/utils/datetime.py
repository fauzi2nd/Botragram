"""
Botragram

Description:
    Datetime and timestamp utility functions.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from datetime import datetime, timezone

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.time import DISPLAY_DATETIME_FORMAT


# =============================================================================
# Utility Functions
# =============================================================================
def current_utc_timestamp_ms() -> int:
    """Get current UTC timestamp in milliseconds.

    Returns:
        Millisecond timestamp as integer.
    """
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def timestamp_ms_to_datetime(ms: int) -> datetime:
    """Convert millisecond timestamp to UTC datetime object.

    Args:
        ms: Millisecond timestamp.

    Returns:
        UTC Datetime object.
    """
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def format_utc_datetime(dt: datetime | None = None) -> str:
    """Format datetime object into display string.

    Args:
        dt: Datetime object or None for current UTC time.

    Returns:
        Formatted UTC datetime string.
    """
    target_dt = dt or datetime.now(timezone.utc)
    return target_dt.strftime(DISPLAY_DATETIME_FORMAT)
