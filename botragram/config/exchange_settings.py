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
from botragram.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT_SECONDS
from botragram.enums import ExchangeType

__all__ = [
    "ExchangeSettings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class ExchangeSettings:
    """Settings for crypto exchange API connection."""

    exchange: ExchangeType = ExchangeType.BYBIT
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    testnet: bool = True
    timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES

    @property
    def is_live(self) -> bool:
        """Whether the application connects to the live exchange."""
        return not self.testnet
