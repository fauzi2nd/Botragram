"""
Botragram

Description:
    Telegram-related exception classes.

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
    "TelegramError",
    "TelegramConfigurationError",
    "TelegramAPIError",
    "TelegramStateError",
    "TelegramCallbackError",
]


# =============================================================================
# Exceptions
# =============================================================================
class TelegramError(BotragramError):
    """Base exception for Telegram-related errors."""


class TelegramConfigurationError(TelegramError):
    """Raised when the Telegram configuration is invalid."""


class TelegramAPIError(TelegramError):
    """Raised when a Telegram Bot API request fails."""


class TelegramStateError(TelegramError):
    """Raised when a Telegram conversation state is invalid."""


class TelegramCallbackError(TelegramError):
    """Raised when a Telegram callback query cannot be processed."""
