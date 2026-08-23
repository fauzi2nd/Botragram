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
    "LiveEntryExistingPositionError",
    "LiveEntryPreflightError",
    "LiveSubmissionBlockedError",
    "VenueRuleValidationError",
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


class LiveEntryExistingPositionError(TradingExecutionError, RuntimeError):
    """Raised when final LIVE entry validation finds an active position."""


class LiveEntryPreflightError(TradingExecutionError, RuntimeError):
    """Raised when LIVE entry preflight fails before mutation can begin."""


class LiveSubmissionBlockedError(TradingExecutionError, RuntimeError):
    """Raised when an incomplete LIVE entry blocks another entry attempt."""


class VenueRuleValidationError(TradingExecutionError, ValueError):
    """Raised when a venue rejects quantity before an order mutation."""


class TradingPositionError(TradingError):
    """Raised when a position operation fails."""


class TradingRiskError(TradingError):
    """Raised when a risk management rule is violated."""


class TradingSignalError(TradingError):
    """Raised when a trading signal cannot be processed."""
