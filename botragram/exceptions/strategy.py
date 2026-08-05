"""
Botragram

Description:
    Strategy-related exception classes.

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
    "StrategyError",
    "StrategyConfigurationError",
    "StrategyValidationError",
    "StrategyExecutionError",
    "StrategySignalError",
    "StrategyNotFoundError",
]


# =============================================================================
# Exceptions
# =============================================================================
class StrategyError(BotragramError):
    """Base exception for strategy-related errors."""


class StrategyConfigurationError(StrategyError):
    """Raised when a strategy configuration is invalid."""


class StrategyValidationError(StrategyError):
    """Raised when strategy validation fails."""


class StrategyExecutionError(StrategyError):
    """Raised when strategy execution fails."""


class StrategySignalError(StrategyError):
    """Raised when a strategy cannot generate a valid trading signal."""


class StrategyNotFoundError(StrategyError):
    """Raised when a requested strategy is unavailable."""
