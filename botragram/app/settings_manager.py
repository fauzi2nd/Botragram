"""
Botragram

Description:
    Settings manager for building application settings from environment.

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
from botragram.app.environment_provider import EnvironmentProvider
from botragram.config.app_settings import AppSettings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.config.market_settings import MarketSettings
from botragram.config.risk_settings import RiskSettings
from botragram.config.strategy_settings import StrategySettings
from botragram.config.telegram_settings import TelegramSettings
from botragram.enums.trade_mode import TradeMode


# =============================================================================
# Manager Class
# =============================================================================
class SettingsManager:
    """Orchestrates configuration loading and instantiation."""

    def __init__(
        self,
        env_provider: EnvironmentProvider | None = None,
    ) -> None:
        """Initialize settings manager.

        Args:
            env_provider: Optional EnvironmentProvider instance.
        """
        self._env_provider = env_provider or EnvironmentProvider()

    def load_app_settings(self) -> AppSettings:
        """Load and return populated AppSettings.

        Returns:
            AppSettings instance.
        """
        mode_str = self._env_provider.get_trade_mode().upper()
        trade_mode = (
            TradeMode.LIVE if mode_str == "LIVE" else TradeMode.PAPER
        )
        return AppSettings(trade_mode=trade_mode)

    def load_exchange_settings(self) -> ExchangeSettings:
        """Load and return populated ExchangeSettings.

        Returns:
            ExchangeSettings instance.
        """
        return ExchangeSettings(
            api_key=self._env_provider.get_api_key(),
            api_secret=self._env_provider.get_api_secret(),
        )

    def load_telegram_settings(self) -> TelegramSettings:
        """Load and return populated TelegramSettings.

        Returns:
            TelegramSettings instance.
        """
        return TelegramSettings(
            bot_token=self._env_provider.get_bot_token(),
        )

    def load_market_settings(self) -> MarketSettings:
        """Load and return default MarketSettings.

        Returns:
            MarketSettings instance.
        """
        return MarketSettings()

    def load_risk_settings(self) -> RiskSettings:
        """Load and return default RiskSettings.

        Returns:
            RiskSettings instance.
        """
        return RiskSettings()

    def load_strategy_settings(self) -> StrategySettings:
        """Load and return default StrategySettings.

        Returns:
            StrategySettings instance.
        """
        return StrategySettings()
