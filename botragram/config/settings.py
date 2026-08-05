"""
Botragram

Description:
    Application configuration.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from dataclasses import dataclass, field

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.ai_settings import AISettings
from botragram.config.app_settings import AppSettings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.config.logging_settings import LoggingSettings
from botragram.config.market_settings import MarketSettings
from botragram.config.risk_settings import RiskSettings
from botragram.config.strategy_settings import StrategySettings
from botragram.config.telegram_settings import TelegramSettings

__all__ = [
    "Settings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class Settings:
    """Application configuration."""

    app: AppSettings = field(default_factory=AppSettings)
    exchange: ExchangeSettings = field(default_factory=ExchangeSettings)
    market: MarketSettings = field(default_factory=MarketSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    strategy: StrategySettings = field(default_factory=StrategySettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    ai: AISettings = field(default_factory=AISettings)
