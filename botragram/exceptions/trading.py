"""
Botragram

Description:
    Trading-related exception classes.

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
    "TradingError",
    "TradingConfigurationError",
    "TradingExecutionError",
    "TradingPositionError",
    "TradingRiskError",
    "TradingSignalError",
]


# =============================================================================
# Exceptions
# =============================================================================
class TradingError(BotragramError):
    """Base exception for trading-related errors."""


class TradingConfigurationError(TradingError):
    """Raised when the trading configuration is invalid."""


class TradingExecutionError(TradingError):
    """Raised when a trading operation cannot be executed."""


class TradingPositionError(TradingError):
    """Raised when a position operation fails."""


class TradingRiskError(TradingError):
    """Raised when a risk management rule is violated."""


class TradingSignalError(TradingError):
    """Raised when a trading signal cannot be processed."""
