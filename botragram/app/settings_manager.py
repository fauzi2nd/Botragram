"""
Botragram

Description:
    Settings manager for building validated application settings from environment.

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
from botragram.config.ai_settings import AISettings
from botragram.config.app_settings import AppSettings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.config.logging_settings import LoggingSettings
from botragram.config.market_settings import MarketSettings
from botragram.config.risk_settings import RiskSettings
from botragram.config.settings import Settings
from botragram.config.strategy_settings import StrategySettings
from botragram.config.telegram_settings import TelegramSettings
from botragram.enums import ExchangeType, LogLevel, TradeMode

__all__ = [
    "SettingsManager",
]


# =============================================================================
# Settings Manager
# =============================================================================
class SettingsManager:
    """Build and validate immutable application settings."""

    __slots__ = ("_environment_provider",)

    def __init__(
        self,
        *,
        environment_provider: EnvironmentProvider | None = None,
    ) -> None:
        """Initialize the settings manager.

        Args:
            environment_provider: Environment variable source. A provider using
                the default dotenv path is created when omitted.
        """
        self._environment_provider = (
            environment_provider
            if environment_provider is not None
            else EnvironmentProvider()
        )

    def load(self) -> Settings:
        """Load, validate, and return the complete application settings.

        Raises:
            ValueError: If an environment value cannot form a valid
                configuration.
        """
        settings = Settings(
            app=self.load_app_settings(),
            exchange=self.load_exchange_settings(),
            market=self.load_market_settings(),
            risk=self.load_risk_settings(),
            strategy=self.load_strategy_settings(),
            telegram=self.load_telegram_settings(),
            logging=self.load_logging_settings(),
            ai=self.load_ai_settings(),
        )
        self.validate(settings=settings)

        return settings

    def load_app_settings(self) -> AppSettings:
        """Load application settings from the environment."""
        return AppSettings(
            trade_mode=self._parse_enum(
                enum_type=TradeMode,
                raw_value=self._environment_provider.get_trade_mode(),
                setting_name="TRADE_MODE",
            ),
        )

    def load_exchange_settings(self) -> ExchangeSettings:
        """Load settings for the configured active exchange."""
        environment = self._environment_provider
        exchange = self._parse_enum(
            enum_type=ExchangeType,
            raw_value=environment.get_active_exchange(),
            setting_name="ACTIVE_EXCHANGE",
        )

        match exchange:
            case ExchangeType.BINANCE:
                return ExchangeSettings(
                    exchange=exchange,
                    api_key=environment.get_binance_api_key(),
                    api_secret=environment.get_binance_api_secret(),
                    testnet=environment.get_binance_testnet(),
                )
            case ExchangeType.BITGET:
                return ExchangeSettings(
                    exchange=exchange,
                    api_key=environment.get_bitget_api_key(),
                    api_secret=environment.get_bitget_api_secret(),
                    passphrase=environment.get_bitget_passphrase(),
                    testnet=environment.get_bitget_testnet(),
                )
            case ExchangeType.BYBIT:
                return ExchangeSettings(
                    exchange=exchange,
                    api_key=environment.get_bybit_api_key(),
                    api_secret=environment.get_bybit_api_secret(),
                    testnet=environment.get_bybit_testnet(),
                )
            case ExchangeType.OKX:
                return ExchangeSettings(
                    exchange=exchange,
                    api_key=environment.get_okx_api_key(),
                    api_secret=environment.get_okx_api_secret(),
                    passphrase=environment.get_okx_passphrase(),
                    testnet=environment.get_okx_testnet(),
                )

    def load_telegram_settings(self) -> TelegramSettings:
        """Load Telegram settings from the environment."""
        token = self._environment_provider.get_telegram_token()
        chat_id = self._environment_provider.get_telegram_chat_id()
        allowed_chat_ids = [self._parse_chat_id(chat_id)] if chat_id else []

        return TelegramSettings(
            bot_token=token,
            allowed_chat_ids=allowed_chat_ids,
            enabled=bool(token),
        )

    def load_market_settings(self) -> MarketSettings:
        """Load market settings using their configured defaults."""
        return MarketSettings()

    def load_risk_settings(self) -> RiskSettings:
        """Load risk settings using their configured defaults."""
        return RiskSettings()

    def load_strategy_settings(self) -> StrategySettings:
        """Load strategy settings using their configured defaults."""
        return StrategySettings()

    def load_logging_settings(self) -> LoggingSettings:
        """Load logging settings from the environment."""
        return LoggingSettings(
            level=self._parse_enum(
                enum_type=LogLevel,
                raw_value=self._environment_provider.get_log_level(),
                setting_name="LOG_LEVEL",
            ),
        )

    def load_ai_settings(self) -> AISettings:
        """Load AI provider settings from the environment."""
        environment = self._environment_provider
        provider = environment.get_ai_provider()
        api_key = self._get_ai_api_key(provider=provider)

        return AISettings(
            enabled=bool(api_key),
            provider=provider.lower(),
            model=environment.get_ai_model() or AISettings().model,
            api_key=api_key,
        )

    @staticmethod
    def validate(
        *,
        settings: Settings,
    ) -> None:
        """Validate settings that require multiple configuration values.

        Args:
            settings: Fully constructed application settings.

        Raises:
            ValueError: If the settings are internally inconsistent.
        """
        has_api_key = bool(settings.exchange.api_key)
        has_api_secret = bool(settings.exchange.api_secret)

        if has_api_key != has_api_secret:
            raise ValueError(
                "Exchange API key and API secret must be configured together"
            )

        if settings.app.trade_mode is TradeMode.LIVE and not has_api_key:
            raise ValueError("Live trading requires exchange API credentials")

        if settings.telegram.enabled and not settings.telegram.bot_token:
            raise ValueError("Enabled Telegram integration requires a bot token")

        if settings.ai.enabled and not settings.ai.api_key:
            raise ValueError("Enabled AI integration requires an API key")

    def _get_ai_api_key(
        self,
        *,
        provider: str,
    ) -> str:
        """Return the credential configured for an AI provider."""
        match provider:
            case "OPENAI":
                return self._environment_provider.get_openai_api_key()
            case "GEMINI":
                return self._environment_provider.get_gemini_api_key()
            case "OPENROUTER":
                return self._environment_provider.get_openrouter_api_key()
            case _:
                raise ValueError(f"Unsupported AI provider: {provider!r}")

    @staticmethod
    def _parse_enum[
        EnumValue: (ExchangeType, LogLevel, TradeMode),
    ](
        *,
        enum_type: type[EnumValue],
        raw_value: str,
        setting_name: str,
    ) -> EnumValue:
        """Parse a case-insensitive string into a supported enum value."""
        try:
            return enum_type(raw_value.lower())
        except ValueError:
            try:
                return enum_type(raw_value.upper())
            except ValueError as error:
                raise ValueError(
                    f"Environment variable {setting_name!r} has invalid value "
                    f"{raw_value!r}"
                ) from error

    @staticmethod
    def _parse_chat_id(
        chat_id: str,
    ) -> int:
        """Parse a configured Telegram chat identifier."""
        try:
            return int(chat_id)
        except ValueError as error:
            raise ValueError(
                "Environment variable 'TELEGRAM_CHAT_ID' must be an integer"
            ) from error
