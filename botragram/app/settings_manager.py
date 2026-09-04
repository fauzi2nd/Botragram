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

from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

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
from botragram.constants.strategy import get_strategy_default_interval
from botragram.enums import (
    ExchangeEnvironment,
    ExchangeType,
    ExecutionPolicy,
    Interval,
    LogLevel,
    MarketType,
    StrategyType,
    TradeMode,
)

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
        app = self.load_app_settings()
        exchange = self.load_exchange_settings()
        strategy = self.load_strategy_settings()
        settings = Settings(
            app=replace(
                app,
                database_path=self._get_scoped_database_path(
                    app=app,
                    exchange=exchange,
                ),
            ),
            exchange=exchange,
            market=self.load_market_settings(strategy_type=strategy.strategy_type),
            risk=self.load_risk_settings(),
            strategy=strategy,
            telegram=self.load_telegram_settings(),
            logging=self.load_logging_settings(),
            ai=self.load_ai_settings(),
        )
        self.validate(settings=settings)

        return settings

    def load_app_settings(self) -> AppSettings:
        """Load application settings from the environment."""
        execution_policy = self._environment_provider.get_execution_policy()
        return AppSettings(
            trade_mode=self._parse_enum(
                enum_type=TradeMode,
                raw_value=self._environment_provider.get_trade_mode(),
                setting_name="TRADE_MODE",
            ),
            autonomous_execution_enabled=(
                self._environment_provider.get_autonomous_execution_enabled()
            ),
            autonomous_live_entry_enabled=(
                self._environment_provider.get_autonomous_live_entry_enabled()
            ),
            autonomous_mainnet_entry_enabled=(
                self._environment_provider.get_autonomous_mainnet_entry_enabled()
            ),
            execution_policy=(
                self._parse_enum(
                    enum_type=ExecutionPolicy,
                    raw_value=execution_policy,
                    setting_name="EXECUTION_POLICY",
                )
                if execution_policy
                else None
            ),
        )

    def load_exchange_settings(
        self,
        *,
        exchange_override: ExchangeType | None = None,
    ) -> ExchangeSettings:
        """Load settings for the configured active exchange or override."""
        environment = self._environment_provider
        exchange = (
            exchange_override
            if exchange_override is not None
            else self._parse_enum(
                enum_type=ExchangeType,
                raw_value=environment.get_active_exchange(),
                setting_name="ACTIVE_EXCHANGE",
            )
        )

        match exchange:
            case ExchangeType.BINANCE:
                market_type = self._parse_enum(
                    enum_type=MarketType,
                    raw_value=environment.get_binance_market_type(),
                    setting_name="BINANCE_MARKET_TYPE",
                )
                return ExchangeSettings(
                    exchange=exchange,
                    market_type=market_type,
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
                market_type = self._parse_enum(
                    enum_type=MarketType,
                    raw_value=environment.get_bybit_market_type(),
                    setting_name="BYBIT_MARKET_TYPE",
                )
                testnet = environment.get_bybit_testnet()
                demo = environment.get_bybit_demo()
                if testnet and demo:
                    raise ValueError(
                        "BYBIT configuration cannot enable both testnet and demo "
                        "simultaneously; set BYBIT_TESTNET=false for demo mode"
                    )
                return ExchangeSettings(
                    exchange=exchange,
                    market_type=market_type,
                    api_key=environment.get_bybit_api_key(),
                    api_secret=environment.get_bybit_api_secret(),
                    testnet=testnet,
                    demo=demo,
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

    def load_market_settings(
        self,
        strategy_type: StrategyType | None = None,
    ) -> MarketSettings:
        """Load market settings while preserving the strategy's optimal interval."""
        environment = self._environment_provider
        raw_interval = environment.get_market_interval()
        raw_discovery_cadence = environment.get_discovery_cadence_seconds()
        default_interval = (
            get_strategy_default_interval(strategy_type)
            if strategy_type is not None
            else Interval.M15
        )
        return MarketSettings(
            interval=(
                self._parse_market_interval(raw_value=raw_interval)
                if raw_interval
                else default_interval
            ),
            discovery_universe_limit=self._parse_positive_int(
                raw_value=environment.get_discovery_universe_limit(),
                setting_name="DISCOVERY_UNIVERSE_LIMIT",
            ),
            discovery_batch_size=self._parse_positive_int(
                raw_value=environment.get_discovery_batch_size(),
                setting_name="DISCOVERY_BATCH_SIZE",
            ),
            discovery_cadence_seconds=(
                self._parse_positive_int(
                    raw_value=raw_discovery_cadence,
                    setting_name="DISCOVERY_CADENCE_SECONDS",
                )
                if raw_discovery_cadence
                else None
            ),
        )

    def load_risk_settings(self) -> RiskSettings:
        """Load validated strategy-specific risk settings."""
        environment = self._environment_provider
        return RiskSettings(
            scalping_stop_loss_pct=self._parse_decimal(
                raw_value=environment.get_scalping_stop_loss_pct(),
                setting_name="SCALPING_STOP_LOSS_PCT",
            ),
            scalping_take_profit_pct=self._parse_decimal(
                raw_value=environment.get_scalping_take_profit_pct(),
                setting_name="SCALPING_TAKE_PROFIT_PCT",
            ),
            trend_stop_loss_pct=self._parse_decimal(
                raw_value=environment.get_trend_stop_loss_pct(),
                setting_name="TREND_STOP_LOSS_PCT",
            ),
            trend_take_profit_pct=self._parse_decimal(
                raw_value=environment.get_trend_take_profit_pct(),
                setting_name="TREND_TAKE_PROFIT_PCT",
            ),
            swing_stop_loss_pct=self._parse_decimal(
                raw_value=environment.get_swing_stop_loss_pct(),
                setting_name="SWING_STOP_LOSS_PCT",
            ),
            swing_take_profit_pct=self._parse_decimal(
                raw_value=environment.get_swing_take_profit_pct(),
                setting_name="SWING_TAKE_PROFIT_PCT",
            ),
            stop_loss_pct=self._parse_decimal(
                raw_value=environment.get_stop_loss_pct(),
                setting_name="STOP_LOSS_PCT",
            ),
            take_profit_pct=self._parse_decimal(
                raw_value=environment.get_take_profit_pct(),
                setting_name="TAKE_PROFIT_PCT",
            ),
            ema_cross_stop_loss_pct=self._parse_decimal(
                raw_value=environment.get_ema_cross_stop_loss_pct(),
                setting_name="EMA_CROSS_STOP_LOSS_PCT",
            ),
            ema_cross_take_profit_pct=self._parse_decimal(
                raw_value=environment.get_ema_cross_take_profit_pct(),
                setting_name="EMA_CROSS_TAKE_PROFIT_PCT",
            ),
            ema_scalping_stop_loss_pct=self._parse_decimal(
                raw_value=environment.get_ema_scalping_stop_loss_pct(),
                setting_name="EMA_SCALPING_STOP_LOSS_PCT",
            ),
            ema_scalping_take_profit_pct=self._parse_decimal(
                raw_value=environment.get_ema_scalping_take_profit_pct(),
                setting_name="EMA_SCALPING_TAKE_PROFIT_PCT",
            ),
            max_open_positions=self._parse_positive_int(
                raw_value=environment.get_max_open_positions(),
                setting_name="MAX_OPEN_POSITIONS",
            ),
            max_position_size_usdt=self._parse_decimal(
                raw_value=environment.get_max_position_size_usdt(),
                setting_name="MAX_POSITION_SIZE_USDT",
            ),
            risk_per_trade_pct=self._parse_decimal(
                raw_value=environment.get_risk_per_trade_pct(),
                setting_name="RISK_PER_TRADE_PCT",
            ),
            max_drawdown_pct=self._parse_decimal(
                raw_value=environment.get_max_drawdown_pct(),
                setting_name="MAX_DRAWDOWN_PCT",
            ),
            leverage=self._parse_positive_int(
                raw_value=environment.get_leverage(),
                setting_name="LEVERAGE",
            ),
            max_executable_quote_age_ms=self._parse_positive_int(
                raw_value=environment.get_max_executable_quote_age_ms(),
                setting_name="MAX_EXECUTABLE_QUOTE_AGE_MS",
            ),
            max_spread_bps=self._parse_decimal(
                raw_value=environment.get_max_spread_bps(),
                setting_name="MAX_SPREAD_BPS",
            ),
        )

    @staticmethod
    def get_scoped_database_path(
        *,
        app: AppSettings,
        exchange: ExchangeSettings,
    ) -> Path:
        """Return a network-scoped SQLite path for every LIVE deployment."""
        if app.trade_mode is not TradeMode.LIVE:
            return app.database_path

        base_path = app.database_path
        scope = "-".join(
            (
                exchange.exchange.value,
                exchange.market_type.value,
                exchange.environment.value,
            )
        )
        return base_path.with_stem(f"{base_path.stem}-{scope}")

    @staticmethod
    def _get_scoped_database_path(
        *,
        app: AppSettings,
        exchange: ExchangeSettings,
    ) -> Path:
        """Backward-compatible alias for get_scoped_database_path."""
        return SettingsManager.get_scoped_database_path(
            app=app,
            exchange=exchange,
        )

    def load_strategy_settings(self) -> StrategySettings:
        """Load strategy settings with strict optional environment selection."""
        raw_strategy_type = self._environment_provider.get_strategy_type()
        invert_signals = self._environment_provider.get_invert_signals()
        min_signal_confidence = self._parse_decimal(
            raw_value=self._environment_provider.get_min_signal_confidence(),
            setting_name="MIN_SIGNAL_CONFIDENCE",
        )
        return StrategySettings(
            strategy_type=(
                self._parse_enum(
                    enum_type=StrategyType,
                    raw_value=raw_strategy_type,
                    setting_name="STRATEGY_TYPE",
                )
                if raw_strategy_type
                else StrategyType.EMA_CROSS
            ),
            invert_signals=invert_signals,
            min_signal_confidence=min_signal_confidence,
        )

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

        policy = settings.app.effective_execution_policy
        legacy_autonomous = settings.app.autonomous_execution_enabled

        if (
            settings.app.execution_policy is ExecutionPolicy.SINGLE_SYMBOL
            and legacy_autonomous
        ):
            raise ValueError(
                "AUTONOMOUS_EXECUTION_ENABLED conflicts with single-symbol "
                "execution policy"
            )

        if (
            settings.app.execution_policy is ExecutionPolicy.HUMAN_CONFIRMED_PAPER
            and legacy_autonomous
        ):
            raise ValueError(
                "AUTONOMOUS_EXECUTION_ENABLED conflicts with human-confirmed "
                "execution policy"
            )

        if (
            policy
            in (
                ExecutionPolicy.AUTONOMOUS_PAPER,
                ExecutionPolicy.HUMAN_CONFIRMED_PAPER,
            )
            and settings.app.trade_mode is TradeMode.LIVE
        ):
            raise ValueError(
                "Autonomous and human-confirmed execution are supported only "
                "in paper mode"
            )

        if policy is ExecutionPolicy.AUTONOMOUS_LIVE:
            if settings.app.trade_mode is not TradeMode.LIVE:
                raise ValueError("Autonomous LIVE execution requires LIVE mode")

            if settings.exchange.market_type is not MarketType.FUTURES:
                raise ValueError("Autonomous LIVE execution requires FUTURES")

            if not settings.app.autonomous_live_entry_enabled:
                raise ValueError("Autonomous LIVE execution requires explicit opt-in")

            if (
                settings.exchange.environment is ExchangeEnvironment.MAINNET
                and not settings.app.autonomous_mainnet_entry_enabled
            ):
                raise ValueError(
                    "Autonomous LIVE execution requires TESTNET or explicit "
                    "MAINNET opt-in"
                )

        if settings.app.autonomous_live_entry_enabled:
            if settings.app.trade_mode is not TradeMode.LIVE:
                raise ValueError(
                    "Autonomous LIVE entry authorization requires LIVE mode"
                )

            if (
                settings.exchange.environment is ExchangeEnvironment.MAINNET
                and not settings.app.autonomous_mainnet_entry_enabled
            ):
                raise ValueError(
                    "Autonomous LIVE entry authorization requires TESTNET or "
                    "explicit MAINNET opt-in"
                )

        if settings.app.autonomous_mainnet_entry_enabled:
            if settings.exchange.environment is not ExchangeEnvironment.MAINNET:
                raise ValueError(
                    "Autonomous MAINNET entry authorization requires MAINNET"
                )
            if not settings.app.autonomous_live_entry_enabled:
                raise ValueError(
                    "Autonomous MAINNET entry authorization requires base LIVE opt-in"
                )
            # The MAINNET flag is an immutable boot capability envelope.
            # The active workflow may remain SINGLE_SYMBOL until a validated
            # in-process switch explicitly selects AUTONOMOUS_LIVE.

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
        EnumValue: (
            ExchangeType,
            ExecutionPolicy,
            LogLevel,
            MarketType,
            StrategyType,
            TradeMode,
        ),
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
    def _parse_market_interval(*, raw_value: str) -> Interval:
        """Parse a case-sensitive Binance candle interval.

        Raises:
            ValueError: If the configured interval is unsupported.
        """
        try:
            return Interval(raw_value)
        except ValueError as error:
            raise ValueError(
                "Environment variable 'MARKET_INTERVAL' has invalid value "
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

    @staticmethod
    def _parse_decimal(*, raw_value: str, setting_name: str) -> Decimal:
        """Parse an exact finite decimal environment ratio."""
        try:
            value = Decimal(raw_value)
        except InvalidOperation as error:
            raise ValueError(
                f"Environment variable {setting_name!r} must be a decimal"
            ) from error

        if not value.is_finite():
            raise ValueError(f"Environment variable {setting_name!r} must be finite")

        return value

    @staticmethod
    def _parse_positive_int(*, raw_value: str, setting_name: str) -> int:
        """Parse one strictly positive integer configuration value."""
        try:
            value = int(raw_value)
        except ValueError as error:
            raise ValueError(
                f"Environment variable {setting_name!r} must be an integer"
            ) from error

        if value <= 0:
            raise ValueError(
                f"Environment variable {setting_name!r} must be greater than zero"
            )

        return value
