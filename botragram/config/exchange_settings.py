"""
Botragram

Description:
    Exchange connection settings model.

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
from dataclasses import dataclass

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.exchange import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
)
from botragram.enums.exchange_type import ExchangeType


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(slots=True)
class ExchangeSettings:
    """Settings for crypto exchange API connection."""

    exchange_type: ExchangeType = ExchangeType.BYBIT
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
    timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
