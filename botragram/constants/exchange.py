"""
Botragram

Description:
    Exchange default configurations and constants.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Constants
# =============================================================================
DEFAULT_REQUEST_TIMEOUT_SECONDS: float = 10.0
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_DELAY_SECONDS: float = 1.0
DEFAULT_WS_RECONNECT_DELAY_SECONDS: float = 5.0
DEFAULT_CANDLE_FETCH_LIMIT: int = 100
