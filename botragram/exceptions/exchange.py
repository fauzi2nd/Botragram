"""
Botragram

Description:
    Exchange-related exception classes.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.exceptions.base import BotragramError

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "ExchangeError",
    "ExchangeAuthenticationError",
    "ExchangeConnectionError",
    "ExchangeRateLimitError",
    "ExchangeRequestError",
    "ExchangeResponseError",
    "ExchangeWebSocketError",
    "ExchangeOrderError",
    "ExchangeInsufficientBalanceError",
    "ExchangeSymbolError",
]


# =============================================================================
# Exceptions
# =============================================================================
class ExchangeError(BotragramError):
    """Base exception for exchange-related errors."""


class ExchangeAuthenticationError(ExchangeError):
    """Raised when exchange authentication fails."""


class ExchangeConnectionError(ExchangeError):
    """Raised when the exchange cannot be reached."""


class ExchangeRateLimitError(ExchangeError):
    """Raised when an exchange rate limit is exceeded."""


class ExchangeRequestError(ExchangeError):
    """Raised when an exchange request is invalid or rejected."""


class ExchangeResponseError(ExchangeError):
    """Raised when an exchange returns an invalid response."""


class ExchangeWebSocketError(ExchangeError):
    """Raised when an exchange WebSocket operation fails."""


class ExchangeOrderError(ExchangeError):
    """Raised when an exchange order operation fails."""


class ExchangeInsufficientBalanceError(ExchangeOrderError):
    """Raised when the account balance is insufficient for an order."""


class ExchangeSymbolError(ExchangeError):
    """Raised when a trading symbol is invalid or unsupported."""
