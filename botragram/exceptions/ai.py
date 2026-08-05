"""
Botragram

Description:
    AI-related exception classes.

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
    "AIError",
    "AIConfigurationError",
    "AIAuthenticationError",
    "AIConnectionError",
    "AIRateLimitError",
    "AIResponseError",
]


# =============================================================================
# Exceptions
# =============================================================================
class AIError(BotragramError):
    """Base exception for AI-related errors."""


class AIConfigurationError(AIError):
    """Raised when the AI configuration is invalid."""


class AIAuthenticationError(AIError):
    """Raised when AI authentication fails."""


class AIConnectionError(AIError):
    """Raised when communication with the AI provider fails."""


class AIRateLimitError(AIError):
    """Raised when the AI provider rate limit is exceeded."""


class AIResponseError(AIError):
    """Raised when the AI provider returns an invalid response."""
