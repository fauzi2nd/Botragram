"""
Botragram

Description:
    Exceptions package initialization.

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
from botragram.exceptions.ai import (
    AIAuthenticationError,
    AIConfigurationError,
    AIConnectionError,
    AIError,
    AIRateLimitError,
    AIResponseError,
)
from botragram.exceptions.base import BotragramError
from botragram.exceptions.config import (
    ConfigError,
    ConfigFileNotFoundError,
    ConfigKeyError,
    ConfigTypeError,
    ConfigValidationError,
)
from botragram.exceptions.exchange import (
    ExchangeAuthenticationError,
    ExchangeConnectionError,
    ExchangeError,
    ExchangeInsufficientBalanceError,
    ExchangeOrderError,
    ExchangeOrderImmediateTriggerRejectedError,
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderPriceBandRejectedError,
    ExchangeOrderRejectedError,
    ExchangeRateLimitError,
    ExchangeRequestError,
    ExchangeResponseError,
    ExchangeSymbolError,
    ExchangeWebSocketError,
)
from botragram.exceptions.indicator import (
    IndicatorCalculationError,
    IndicatorConfigurationError,
    IndicatorDataError,
    IndicatorError,
    IndicatorNotFoundError,
)
from botragram.exceptions.strategy import (
    StrategyConfigurationError,
    StrategyError,
    StrategyExecutionError,
    StrategyNotFoundError,
    StrategySignalError,
    StrategyValidationError,
)
from botragram.exceptions.telegram import (
    TelegramAPIError,
    TelegramCallbackError,
    TelegramConfigurationError,
    TelegramError,
    TelegramStateError,
)
from botragram.exceptions.trading import (
    LiveEntryExistingPositionError,
    LiveEntryPortfolioCapacityError,
    LiveEntryPreflightError,
    LiveSubmissionBlockedError,
    TradingConfigurationError,
    TradingError,
    TradingExecutionError,
    TradingPositionError,
    TradingRiskError,
    TradingSignalError,
    VenueRuleValidationError,
)

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    # Base Exception
    "BotragramError",
    # AI Exceptions
    "AIError",
    "AIConfigurationError",
    "AIAuthenticationError",
    "AIConnectionError",
    "AIRateLimitError",
    "AIResponseError",
    # Config Exceptions
    "ConfigError",
    "ConfigFileNotFoundError",
    "ConfigKeyError",
    "ConfigTypeError",
    "ConfigValidationError",
    # Exchange Exceptions
    "ExchangeError",
    "ExchangeAuthenticationError",
    "ExchangeConnectionError",
    "ExchangeRateLimitError",
    "ExchangeRequestError",
    "ExchangeResponseError",
    "ExchangeWebSocketError",
    "ExchangeOrderError",
    "ExchangeOrderNotFoundError",
    "ExchangeOrderOutcomeUnknownError",
    "ExchangeOrderRejectedError",
    "ExchangeOrderImmediateTriggerRejectedError",
    "ExchangeOrderPriceBandRejectedError",
    "ExchangeInsufficientBalanceError",
    "ExchangeSymbolError",
    # Indicator Exceptions
    "IndicatorError",
    "IndicatorConfigurationError",
    "IndicatorDataError",
    "IndicatorCalculationError",
    "IndicatorNotFoundError",
    # Strategy Exceptions
    "StrategyError",
    "StrategyConfigurationError",
    "StrategyValidationError",
    "StrategyExecutionError",
    "StrategySignalError",
    "StrategyNotFoundError",
    # Telegram Exceptions
    "TelegramError",
    "TelegramConfigurationError",
    "TelegramAPIError",
    "TelegramStateError",
    "TelegramCallbackError",
    # Trading Exceptions
    "TradingError",
    "TradingConfigurationError",
    "TradingExecutionError",
    "LiveEntryExistingPositionError",
    "LiveEntryPortfolioCapacityError",
    "LiveEntryPreflightError",
    "LiveSubmissionBlockedError",
    "VenueRuleValidationError",
    "TradingPositionError",
    "TradingRiskError",
    "TradingSignalError",
]
