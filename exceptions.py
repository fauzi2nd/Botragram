"""
Trading Bot

Module:
    core.exceptions

Description:
    Shared exception hierarchy used throughout the trading bot.

Python:
    3.14
"""

from __future__ import annotations

__all__ = [
    "TradingBotError",
    "ValidationError",
    "ConfigurationError",
    "ExchangeError",
    "StorageError",
    "SerializationError",
    "AnalysisError",
    "ExecutionError",
    "StrategyError",
    "TelegramError",
]


class TradingBotError(Exception):
    """Base exception for the trading bot."""


class ValidationError(TradingBotError):
    """Raised when validation fails."""


class ConfigurationError(TradingBotError):
    """Raised when application configuration is invalid."""


class ExchangeError(TradingBotError):
    """Raised when an exchange operation fails."""


class StorageError(TradingBotError):
    """Raised when a storage operation fails."""


class SerializationError(TradingBotError):
    """Raised when serialization or deserialization fails."""


class AnalysisError(TradingBotError):
    """Raised when market analysis fails."""


class ExecutionError(TradingBotError):
    """Raised when order execution fails."""


class StrategyError(TradingBotError):
    """Raised when a strategy fails."""


class TelegramError(TradingBotError):
    """Raised when a Telegram operation fails."""