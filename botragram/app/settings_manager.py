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
from botragram.enums.exchange_type import ExchangeType
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

    def load_exchange_settings(
        self,
        exchange_type: ExchangeType | None = None,
    ) -> ExchangeSettings:
        """Load and return ExchangeSettings for specified or active exchange.

        Args:
            exchange_type: Optional ExchangeType override. If None, reads EXCHANGE from env.

        Returns:
            ExchangeSettings instance populated with correct credentials.
        """
        env = self._env_provider
        if exchange_type is None:
            active = env.get_active_exchange()
            try:
                exchange_type = ExchangeType(active.lower())
            except ValueError:
                exchange_type = ExchangeType.BYBIT

        if exchange_type == ExchangeType.BINANCE:
            return ExchangeSettings(
                exchange_type=ExchangeType.BINANCE,
                api_key=env.get_binance_api_key(),
                api_secret=env.get_binance_api_secret(),
                testnet=env.get_binance_testnet(),
            )
        if exchange_type == ExchangeType.OKX:
            return ExchangeSettings(
                exchange_type=ExchangeType.OKX,
                api_key=env.get_okx_api_key(),
                api_secret=env.get_okx_api_secret(),
                passphrase=env.get_okx_passphrase(),
                testnet=env.get_okx_testnet(),
            )
        if exchange_type == ExchangeType.BITGET:
            return ExchangeSettings(
                exchange_type=ExchangeType.BITGET,
                api_key=env.get_bitget_api_key(),
                api_secret=env.get_bitget_api_secret(),
                passphrase=env.get_bitget_passphrase(),
                testnet=env.get_bitget_testnet(),
            )
        # Default: BYBIT
        return ExchangeSettings(
            exchange_type=ExchangeType.BYBIT,
            api_key=env.get_bybit_api_key(),
            api_secret=env.get_bybit_api_secret(),
            testnet=env.get_bybit_testnet(),
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
