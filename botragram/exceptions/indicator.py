"""
Botragram

Description:
    Indicator-related exception classes.

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
    "IndicatorError",
    "IndicatorConfigurationError",
    "IndicatorDataError",
    "IndicatorCalculationError",
    "IndicatorNotFoundError",
]


# =============================================================================
# Exceptions
# =============================================================================
class IndicatorError(BotragramError):
    """Base exception for indicator-related errors."""


class IndicatorConfigurationError(IndicatorError):
    """Raised when indicator configuration is invalid."""


class IndicatorDataError(IndicatorError):
    """Raised when indicator input data is invalid or insufficient."""


class IndicatorCalculationError(IndicatorError):
    """Raised when an indicator calculation fails."""


class IndicatorNotFoundError(IndicatorError):
    """Raised when a requested indicator is unavailable."""
