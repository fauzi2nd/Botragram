"""
Botragram

Description:
    Trading-related exception classes.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.exceptions.base import BotragramError

__all__ = [
    "TradingError",
    "TradingConfigurationError",
    "TradingExecutionError",
    "ExecutionPolicySwitchBlockedError",
    "LiveEntryExistingPositionError",
    "LiveEntryPortfolioCapacityError",
    "LiveEntryPreflightError",
    "LiveEntryRiskLimitError",
    "LiveEntrySymbolReadinessError",
    "LiveSubmissionBlockedError",
    "OperatorExitConfirmationUnavailableError",
    "VenueRuleValidationError",
    "TradingPositionError",
    "TradingRiskError",
    "TradingSignalError",
]


class TradingError(BotragramError):
    """Base exception for trading-related errors."""


class TradingConfigurationError(TradingError):
    """Raised when the trading configuration is invalid."""


class TradingExecutionError(TradingError):
    """Raised when a trading operation cannot be executed."""


class ExecutionPolicySwitchBlockedError(TradingConfigurationError, RuntimeError):
    """Raised for an expected operator-correctable policy transition blocker."""

    def __init__(
        self,
        message: str,
        *,
        active_position_count: int = 0,
    ) -> None:
        """Initialize one typed transition rejection.

        Args:
            message: Human-readable reason the transition remains blocked.
            active_position_count: Authoritative positions preventing the switch.

        Raises:
            ValueError: If the position count is negative.
        """
        if active_position_count < 0:
            raise ValueError("Active position count must not be negative")
        super().__init__(message)
        self._active_position_count = active_position_count

    @property
    def active_position_count(self) -> int:
        """Return the authoritative count that enables guarded flatten UX."""
        return self._active_position_count


class LiveEntryExistingPositionError(TradingExecutionError, RuntimeError):
    """Raised when final LIVE entry validation finds an active position."""


class LiveEntryPortfolioCapacityError(TradingExecutionError, RuntimeError):
    """Raised when final LIVE validation finds no portfolio capacity."""


class LiveEntryPreflightError(TradingExecutionError, RuntimeError):
    """Raised when LIVE entry preflight fails before mutation can begin."""


class LiveEntryRiskLimitError(LiveEntryPreflightError):
    """Raised when the runtime canary limit deterministically rejects an entry."""


class LiveEntrySymbolReadinessError(LiveEntryPreflightError):
    """Raised when existing MAINNET symbol settings deterministically reject entry."""


class LiveSubmissionBlockedError(TradingExecutionError, RuntimeError):
    """Raised when an incomplete LIVE entry blocks another entry attempt."""


class OperatorExitConfirmationUnavailableError(TradingExecutionError, RuntimeError):
    """Raised when a process-local operator confirmation is no longer present."""


class VenueRuleValidationError(TradingExecutionError, ValueError):
    """Raised when a venue rejects quantity before an order mutation."""


class TradingPositionError(TradingError):
    """Raised when a position operation fails."""


class TradingRiskError(TradingError):
    """Raised when a risk management rule is violated."""


class TradingSignalError(TradingError):
    """Raised when a trading signal cannot be processed."""
