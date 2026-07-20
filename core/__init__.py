"""
Trading Bot

Package:
    core

Description:
    Core components shared across the trading bot.

Python:
    3.14
"""

from __future__ import annotations

from core.exceptions import (
    AnalysisError,
    ConfigurationError,
    ExchangeError,
    ExecutionError,
    SerializationError,
    StorageError,
    StrategyError,
    TelegramError,
    TradingBotError,
    ValidationError,
)

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