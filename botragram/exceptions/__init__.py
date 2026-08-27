"""
Botragram

Description:
    Exceptions package initialization.

Python:
    3.14+
"""

from __future__ import annotations

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
    LiveEntryRiskLimitError,
    LiveEntrySymbolReadinessError,
    LiveSubmissionBlockedError,
    TradingConfigurationError,
    TradingError,
    TradingExecutionError,
    TradingPositionError,
    TradingRiskError,
    TradingSignalError,
    VenueRuleValidationError,
)

__all__ = [
    "BotragramError",
    "AIError",
    "AIConfigurationError",
    "AIAuthenticationError",
    "AIConnectionError",
    "AIRateLimitError",
    "AIResponseError",
    "ConfigError",
    "ConfigFileNotFoundError",
    "ConfigKeyError",
    "ConfigTypeError",
    "ConfigValidationError",
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
    "IndicatorError",
    "IndicatorConfigurationError",
    "IndicatorDataError",
    "IndicatorCalculationError",
    "IndicatorNotFoundError",
    "StrategyError",
    "StrategyConfigurationError",
    "StrategyValidationError",
    "StrategyExecutionError",
    "StrategySignalError",
    "StrategyNotFoundError",
    "TelegramError",
    "TelegramConfigurationError",
    "TelegramAPIError",
    "TelegramStateError",
    "TelegramCallbackError",
    "TradingError",
    "TradingConfigurationError",
    "TradingExecutionError",
    "LiveEntryExistingPositionError",
    "LiveEntryPortfolioCapacityError",
    "LiveEntryPreflightError",
    "LiveEntryRiskLimitError",
    "LiveEntrySymbolReadinessError",
    "LiveSubmissionBlockedError",
    "VenueRuleValidationError",
    "TradingPositionError",
    "TradingRiskError",
    "TradingSignalError",
]
