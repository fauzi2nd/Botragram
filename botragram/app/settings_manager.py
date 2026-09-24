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

import logging
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

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
from botragram.constants import DEFAULT_DISCOVERY_CANDLE_DELAY_SECONDS
from botragram.enums import (
    ExchangeEnvironment,
    ExchangeType,
    ExecutionPolicy,
    Interval,
    LogLevel,
    MarginMode,
    MarketType,
    StrategyType,
    TradeMode,
)

__all__ = [
    "SettingsManager",
]

_LOGGER: Final[logging.Logger] = logging.getLogger("botragram.app.settings_manager")


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
            market=self.load_market_settings(
                strategy_type=strategy.strategy_type,
                exchange=exchange,
            ),
            risk=self.load_risk_settings(),
            strategy=strategy,
            telegram=self.load_telegram_settings(),
            logging=self.load_logging_settings(
                app=app,
                exchange=exchange,
            ),
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
                market_type = self._parse_enum(
                    enum_type=MarketType,
                    raw_value=environment.get_bitget_market_type(),
                    setting_name="BITGET_MARKET_TYPE",
                )
                margin_mode = self._parse_enum(
                    enum_type=MarginMode,
                    raw_value=environment.get_bitget_margin_mode(),
                    setting_name="BITGET_MARGIN_MODE",
                )
                cfd_mode = environment.get_bitget_cfd_mode()
                return ExchangeSettings(
                    exchange=exchange,
                    market_type=market_type,
                    api_key=environment.get_bitget_api_key(),
                    api_secret=environment.get_bitget_api_secret(),
                    passphrase=environment.get_bitget_passphrase(),
                    testnet=environment.get_bitget_testnet(),
                    margin_mode=margin_mode,
                    cfd_mode=cfd_mode,
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
        *,
        exchange: ExchangeSettings | None = None,
    ) -> MarketSettings:
        """Load market settings defining global market timeframe and discovery."""
        del strategy_type
        environment = self._environment_provider
        if environment.has_legacy_market_interval_only():
            _LOGGER.warning(
                "Environment variable 'MARKET_INTERVAL' is deprecated; "
                "use 'GLOBAL_MARKET_INTERVAL' instead."
            )
        raw_interval = environment.get_global_market_interval()
        raw_max_universe_symbols = environment.get_discovery_max_universe_symbols()
        raw_discovery_cadence = environment.get_discovery_cadence_seconds()
        raw_candle_delay = environment.get_discovery_candle_delay_seconds()
        default_interval = Interval.M5
        setting_name = (
            "MARKET_INTERVAL"
            if environment.has_legacy_market_interval_only()
            else "GLOBAL_MARKET_INTERVAL"
        )

        market_type = (
            exchange.market_type if exchange is not None else MarketType.FUTURES
        )

        cfd_symbol = environment.get_cfd_symbol().strip().upper()
        futures_symbol = environment.get_futures_symbol().strip().upper()
        spot_symbol = environment.get_spot_symbol().strip().upper()

        if market_type is MarketType.CFD and cfd_symbol:
            raw_symbol = cfd_symbol
        elif market_type is MarketType.FUTURES and futures_symbol:
            raw_symbol = futures_symbol
        elif market_type is MarketType.SPOT and spot_symbol:
            raw_symbol = spot_symbol
        else:
            raw_symbol = environment.get_market_symbol().strip().upper()

        cfd_quote = environment.get_cfd_quote_asset().strip().upper()
        futures_quote = environment.get_futures_quote_asset().strip().upper()
        if market_type is MarketType.CFD and cfd_quote:
            raw_quote = cfd_quote
        elif market_type is MarketType.FUTURES and futures_quote:
            raw_quote = futures_quote
        else:
            raw_quote = environment.get_quote_asset().strip().upper()

        raw_base = environment.get_base_asset().strip().upper()

        if raw_base and raw_quote:
            base_asset = raw_base
            quote_asset = raw_quote
        elif raw_symbol:
            if market_type is MarketType.CFD:
                if raw_symbol.endswith("USDT"):
                    base_asset = raw_symbol[:-4]
                elif raw_symbol.endswith("USD"):
                    base_asset = raw_symbol[:-3]
                else:
                    base_asset = raw_symbol
                quote_asset = raw_quote or "USD"
            else:
                if raw_symbol.endswith("USDT"):
                    base_asset = raw_symbol[:-4]
                    quote_asset = raw_quote or "USDT"
                elif raw_symbol.endswith("USD"):
                    base_asset = raw_symbol[:-3]
                    quote_asset = raw_quote or "USDT"
                elif raw_symbol.endswith("USDC"):
                    base_asset = raw_symbol[:-4]
                    quote_asset = raw_quote or "USDC"
                else:
                    base_asset = raw_symbol
                    quote_asset = raw_quote or "USDT"
        elif market_type is MarketType.CFD:
            base_asset = "XAU"
            quote_asset = raw_quote or "USD"
        else:
            base_asset = "BTC"
            quote_asset = raw_quote or "USDT"

        return MarketSettings(
            base_asset=base_asset,
            quote_asset=quote_asset,
            interval=(
                self._parse_market_interval(
                    raw_value=raw_interval,
                    setting_name=setting_name,
                )
                if raw_interval
                else default_interval
            ),
            discovery_universe_limit=self._parse_positive_int(
                raw_value=environment.get_discovery_universe_limit(),
                setting_name="DISCOVERY_UNIVERSE_LIMIT",
            ),
            discovery_max_universe_symbols=(
                self._parse_positive_int(
                    raw_value=raw_max_universe_symbols,
                    setting_name="DISCOVERY_MAX_UNIVERSE_SYMBOLS",
                )
                if raw_max_universe_symbols
                else None
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
            discovery_candle_delay_seconds=(
                self._parse_non_negative_float(
                    raw_value=raw_candle_delay,
                    setting_name="DISCOVERY_CANDLE_DELAY_SECONDS",
                )
                if raw_candle_delay
                else DEFAULT_DISCOVERY_CANDLE_DELAY_SECONDS
            ),
            candle_retention_days=self._parse_positive_int(
                raw_value=environment.get_candle_retention_days(),
                setting_name="CANDLE_RETENTION_DAYS",
            ),
            candle_pruning_interval_hours=self._parse_positive_int(
                raw_value=environment.get_candle_pruning_interval_hours(),
                setting_name="CANDLE_PRUNING_INTERVAL_HOURS",
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
            pier_stop_loss_pct=self._parse_decimal(
                raw_value=environment.get_pier_stop_loss_pct(),
                setting_name="PIER_STOP_LOSS_PCT",
            ),
            pier_take_profit_pct=self._parse_decimal(
                raw_value=environment.get_pier_take_profit_pct(),
                setting_name="PIER_TAKE_PROFIT_PCT",
            ),
            origin_stop_loss_pct=self._resolve_origin_stop_loss_pct(),
            origin_take_profit_pct=self._resolve_origin_take_profit_pct(),
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
            stepped_stop_enabled=environment.get_stepped_stop_enabled(),
            stepped_stop_thresholds=self._parse_decimal_tuple(
                raw_value=environment.get_stepped_stop_thresholds(),
                setting_name="STEPPED_STOP_THRESHOLDS",
            ),
            stepped_stop_locked_lag=self._parse_decimal(
                raw_value=environment.get_stepped_stop_locked_lag(),
                setting_name="STEPPED_STOP_LOCKED_LAG",
            ),
            breakeven_roi_threshold=self._parse_decimal(
                raw_value=environment.get_breakeven_roi_threshold(),
                setting_name="BREAKEVEN_ROI_THRESHOLD",
            ),
            breakeven_fee_buffer=self._parse_decimal(
                raw_value=environment.get_breakeven_fee_buffer(),
                setting_name="BREAKEVEN_FEE_BUFFER",
            ),
            partial_tp_enabled=environment.get_partial_tp_enabled(),
            partial_tp_ratio=self._parse_decimal(
                raw_value=environment.get_partial_tp_ratio(),
                setting_name="PARTIAL_TP_RATIO",
            ),
            partial_tp_trigger_progress=self._parse_decimal(
                raw_value=environment.get_partial_tp_trigger_progress(),
                setting_name="PARTIAL_TP_TRIGGER_PROGRESS",
            ),
            enable_early_position_exit=environment.get_enable_early_position_exit(),
            early_exit_min_confidence=self._parse_non_negative_float(
                raw_value=environment.get_early_exit_min_confidence(),
                setting_name="EARLY_EXIT_MIN_CONFIDENCE",
            ),
            early_exit_check_candlestick_reversal=(
                environment.get_early_exit_check_candlestick_reversal()
            ),
            early_exit_check_opposite_signal=(
                environment.get_early_exit_check_opposite_signal()
            ),
            volatility_sizing_enabled=environment.get_volatility_sizing_enabled(),
            baseline_volatility_pct=self._parse_decimal(
                raw_value=environment.get_baseline_volatility_pct(),
                setting_name="BASELINE_VOLATILITY_PCT",
            ),
            dynamic_sizing_enabled=environment.get_dynamic_sizing_enabled(),
            confidence_sizing_enabled=environment.get_confidence_sizing_enabled(),
            baseline_confidence=self._parse_decimal(
                raw_value=environment.get_baseline_confidence(),
                setting_name="BASELINE_CONFIDENCE",
            ),
            max_confidence_multiplier=self._parse_decimal(
                raw_value=environment.get_max_confidence_multiplier(),
                setting_name="MAX_CONFIDENCE_MULTIPLIER",
            ),
            dynamic_leverage_enabled=environment.get_dynamic_leverage_enabled(),
            min_leverage=self._parse_positive_int(
                raw_value=environment.get_min_leverage(),
                setting_name="MIN_LEVERAGE",
            ),
            max_leverage=self._parse_positive_int(
                raw_value=environment.get_max_leverage(),
                setting_name="MAX_LEVERAGE",
            ),
            slot_sizing_enabled=environment.get_slot_sizing_enabled(),
            slot_margin_buffer_pct=self._parse_decimal(
                raw_value=environment.get_slot_margin_buffer_pct(),
                setting_name="SLOT_MARGIN_BUFFER_PCT",
            ),
            min_order_notional_usdt=self._parse_decimal(
                raw_value=environment.get_min_order_notional_usdt(),
                setting_name="MIN_ORDER_NOTIONAL_USDT",
            ),
        )

    def _resolve_origin_stop_loss_pct(self) -> Decimal:
        environment = self._environment_provider
        raw_val = (
            environment.get_origin_stop_loss_pct()
            or environment.get_origin_max_sl_pct()
            or environment.get_origin_fallback_sl_pct()
        )
        return (
            self._parse_decimal(
                raw_value=raw_val,
                setting_name="ORIGIN_STOP_LOSS_PCT",
            )
            if raw_val
            else Decimal("0.030")
        )

    def _resolve_origin_take_profit_pct(self) -> Decimal:
        environment = self._environment_provider
        raw_tp = environment.get_origin_take_profit_pct()
        if raw_tp:
            return self._parse_decimal(
                raw_value=raw_tp,
                setting_name="ORIGIN_TAKE_PROFIT_PCT",
            )
        raw_rrr = environment.get_origin_risk_reward_ratio()
        rrr = (
            self._parse_decimal(
                raw_value=raw_rrr,
                setting_name="ORIGIN_RISK_REWARD_RATIO",
            )
            if raw_rrr
            else Decimal("1.5")
        )
        return self._resolve_origin_stop_loss_pct() * rrr

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

    @staticmethod
    def get_scoped_log_filename(
        *,
        app: AppSettings,
        exchange: ExchangeSettings,
    ) -> str:
        """Return environment-scoped log filename for isolated concurrent runs."""
        if app.trade_mode is TradeMode.PAPER:
            return "botragram-paper.log"

        if (
            exchange.testnet
            or exchange.demo
            or exchange.environment is ExchangeEnvironment.TESTNET
        ):
            return "botragram-testnet.log"

        return "botragram-live.log"

    @staticmethod
    def resolve_strategy_interval_from_environment(
        strategy_type: StrategyType,
        environment_provider: EnvironmentProvider | None = None,
    ) -> tuple[Interval | None, str | None]:
        """Resolve candle interval and source name configured for a strategy type."""
        provider = (
            environment_provider
            if environment_provider is not None
            else EnvironmentProvider()
        )
        raw_strat_interval, strat_interval_source = provider.get_strategy_interval(
            strategy_type
        )
        strategy_interval: Interval | None = None
        if raw_strat_interval and raw_strat_interval.strip():
            strategy_interval = SettingsManager._parse_market_interval(
                raw_value=raw_strat_interval.strip(),
                setting_name=strat_interval_source,
            )
        return (
            strategy_interval,
            strat_interval_source if strategy_interval is not None else None,
        )

    def resolve_strategy_interval(
        self,
        strategy_type: StrategyType,
    ) -> tuple[Interval | None, str | None]:
        """Resolve candle interval and source name for the configured environment."""
        return self.resolve_strategy_interval_from_environment(
            strategy_type=strategy_type,
            environment_provider=self._environment_provider,
        )

    def load_strategy_settings(self) -> StrategySettings:
        """Load strategy settings with strict optional environment selection."""
        environment = self._environment_provider
        raw_strategy_type = environment.get_strategy_type()
        strategy_type = (
            self._parse_enum(
                enum_type=StrategyType,
                raw_value=raw_strategy_type,
                setting_name="STRATEGY_TYPE",
            )
            if raw_strategy_type
            else StrategyType.EMA_CROSS
        )
        strategy_interval, strat_interval_source = self.resolve_strategy_interval(
            strategy_type
        )
        strategy_override_enabled = (
            environment.get_strategy_timeframe_override_enabled()
        )
        raw_strategy_override = environment.get_strategy_timeframe_override()
        timeframe_override: Interval | None = None
        if strategy_override_enabled:
            if not raw_strategy_override or not raw_strategy_override.strip():
                raise ValueError(
                    "Environment variable 'STRATEGY_TIMEFRAME_OVERRIDE' cannot "
                    "be empty when 'STRATEGY_TIMEFRAME_OVERRIDE_ENABLED' is true"
                )
            timeframe_override = self._parse_market_interval(
                raw_value=raw_strategy_override.strip(),
                setting_name="STRATEGY_TIMEFRAME_OVERRIDE",
            )
        elif raw_strategy_override and raw_strategy_override.strip():
            timeframe_override = self._parse_market_interval(
                raw_value=raw_strategy_override.strip(),
                setting_name="STRATEGY_TIMEFRAME_OVERRIDE",
            )
        invert_signals = environment.get_invert_signals()
        min_signal_confidence = self._parse_decimal(
            raw_value=self._environment_provider.get_min_signal_confidence(),
            setting_name="MIN_SIGNAL_CONFIDENCE",
        )
        mtf_enabled = self._environment_provider.get_mtf_confirmation_enabled()
        raw_mtf_interval = self._environment_provider.get_mtf_interval()
        mtf_interval = (
            self._parse_enum(
                enum_type=Interval,
                raw_value=raw_mtf_interval,
                setting_name="MTF_TIMEFRAME",
            )
            if raw_mtf_interval
            else Interval.H1
        )
        mtf_ema_period = self._parse_positive_int(
            raw_value=self._environment_provider.get_mtf_ema_period(),
            setting_name="MTF_EMA_PERIOD",
        )
        btc_trend_filter_enabled = (
            self._environment_provider.get_btc_trend_filter_enabled()
        )
        raw_btc_trend_interval = self._environment_provider.get_btc_trend_interval()
        btc_trend_interval = (
            self._parse_enum(
                enum_type=Interval,
                raw_value=raw_btc_trend_interval,
                setting_name="BTC_TREND_INTERVAL",
            )
            if raw_btc_trend_interval
            else Interval.M15
        )
        btc_trend_ema_period = self._parse_positive_int(
            raw_value=self._environment_provider.get_btc_trend_ema_period(),
            setting_name="BTC_TREND_EMA_PERIOD",
        )
        discovery_filter_extreme_volatility = (
            self._environment_provider.get_discovery_filter_extreme_volatility()
        )
        discovery_max_candle_volatility_pct = self._parse_decimal(
            raw_value=(
                self._environment_provider.get_discovery_max_candle_volatility_pct()
            ),
            setting_name="DISCOVERY_MAX_CANDLE_VOLATILITY_PCT",
        )
        discovery_filter_min_liquidity = (
            self._environment_provider.get_discovery_filter_min_liquidity()
        )
        discovery_min_quote_volume_usdt = self._parse_decimal(
            raw_value=(
                self._environment_provider.get_discovery_min_quote_volume_usdt()
            ),
            setting_name="DISCOVERY_MIN_QUOTE_VOLUME_USDT",
        )
        discovery_use_dynamic_volume = (
            self._environment_provider.get_discovery_use_dynamic_volume()
        )
        discovery_volume_sma_period = self._parse_positive_int(
            raw_value=self._environment_provider.get_discovery_volume_sma_period(),
            setting_name="DISCOVERY_VOLUME_SMA_PERIOD",
        )
        discovery_min_24h_turnover_usdt = self._parse_decimal(
            raw_value=(
                self._environment_provider.get_discovery_min_24h_turnover_usdt()
            ),
            setting_name="DISCOVERY_MIN_24H_TURNOVER_USDT",
        )
        use_open_interest = self._environment_provider.get_use_open_interest()
        min_oi_change_pct = self._parse_decimal(
            raw_value=self._environment_provider.get_min_oi_change_pct(),
            setting_name="MIN_OI_CHANGE_PCT",
        )
        require_oi_confluence = self._environment_provider.get_require_oi_confluence()
        filter_funding_sentiment = (
            self._environment_provider.get_filter_funding_sentiment()
        )
        max_long_funding_rate = self._parse_decimal(
            raw_value=self._environment_provider.get_max_long_funding_rate(),
            setting_name="MAX_LONG_FUNDING_RATE",
        )
        min_short_funding_rate = self._parse_decimal(
            raw_value=self._environment_provider.get_min_short_funding_rate(),
            setting_name="MIN_SHORT_FUNDING_RATE",
        )
        require_funding_sentiment = (
            self._environment_provider.get_require_funding_sentiment()
        )
        filter_account_ratio = self._environment_provider.get_filter_account_ratio()
        max_long_account_ratio = self._parse_decimal(
            raw_value=self._environment_provider.get_max_long_account_ratio(),
            setting_name="MAX_LONG_ACCOUNT_RATIO",
        )
        min_short_account_ratio = self._parse_decimal(
            raw_value=self._environment_provider.get_min_short_account_ratio(),
            setting_name="MIN_SHORT_ACCOUNT_RATIO",
        )
        require_account_ratio_confluence = (
            self._environment_provider.get_require_account_ratio_confluence()
        )
        confirm_htf_account_ratio = (
            self._environment_provider.get_confirm_htf_account_ratio()
        )
        account_ratio_htf_period = (
            self._environment_provider.get_account_ratio_htf_period()
        )
        return StrategySettings(
            strategy_type=strategy_type,
            strategy_interval=strategy_interval,
            strategy_interval_source=(
                strat_interval_source if strategy_interval is not None else None
            ),
            timeframe_override_enabled=strategy_override_enabled,
            timeframe_override=timeframe_override,
            invert_signals=invert_signals,
            min_signal_confidence=min_signal_confidence,
            mtf_confirmation_enabled=mtf_enabled,
            mtf_interval=mtf_interval,
            mtf_ema_period=mtf_ema_period,
            btc_trend_filter_enabled=btc_trend_filter_enabled,
            btc_trend_interval=btc_trend_interval,
            btc_trend_ema_period=btc_trend_ema_period,
            discovery_filter_extreme_volatility=(discovery_filter_extreme_volatility),
            discovery_max_candle_volatility_pct=(discovery_max_candle_volatility_pct),
            discovery_filter_min_liquidity=discovery_filter_min_liquidity,
            discovery_min_quote_volume_usdt=discovery_min_quote_volume_usdt,
            discovery_use_dynamic_volume=discovery_use_dynamic_volume,
            discovery_volume_sma_period=discovery_volume_sma_period,
            discovery_min_24h_turnover_usdt=discovery_min_24h_turnover_usdt,
            use_open_interest=use_open_interest,
            min_oi_change_pct=min_oi_change_pct,
            require_oi_confluence=require_oi_confluence,
            filter_funding_sentiment=filter_funding_sentiment,
            max_long_funding_rate=max_long_funding_rate,
            min_short_funding_rate=min_short_funding_rate,
            require_funding_sentiment=require_funding_sentiment,
            filter_account_ratio=filter_account_ratio,
            max_long_account_ratio=max_long_account_ratio,
            min_short_account_ratio=min_short_account_ratio,
            require_account_ratio_confluence=require_account_ratio_confluence,
            confirm_htf_account_ratio=confirm_htf_account_ratio,
            account_ratio_htf_period=account_ratio_htf_period,
            pier_confirm_htf_account_ratio=confirm_htf_account_ratio,
            pier_rsi_long_min=self._parse_decimal(
                raw_value=environment.get_pier_rsi_long_min(),
                setting_name="PIER_RSI_LONG_MIN",
            ),
            pier_rsi_long_max=self._parse_decimal(
                raw_value=environment.get_pier_rsi_long_max(),
                setting_name="PIER_RSI_LONG_MAX",
            ),
            pier_rsi_short_min=self._parse_decimal(
                raw_value=environment.get_pier_rsi_short_min(),
                setting_name="PIER_RSI_SHORT_MIN",
            ),
            pier_rsi_short_max=self._parse_decimal(
                raw_value=environment.get_pier_rsi_short_max(),
                setting_name="PIER_RSI_SHORT_MAX",
            ),
            pier_use_macd=environment.get_pier_use_macd(),
            pier_use_stoch_rsi=environment.get_pier_use_stoch_rsi(),
            ny_range_risk_reward_ratio=(
                self._parse_decimal(
                    raw_value=environment.get_ny_range_risk_reward_ratio(),
                    setting_name="NY_RANGE_RISK_REWARD_RATIO",
                )
                if environment.get_ny_range_risk_reward_ratio()
                else Decimal("0.8")
            ),
            ny_range_max_sl_pct=(
                self._parse_decimal(
                    raw_value=environment.get_ny_range_max_sl_pct(),
                    setting_name="NY_RANGE_MAX_SL_PCT",
                )
                if environment.get_ny_range_max_sl_pct()
                else Decimal("0.03")
            ),
            ny_range_min_sl_pct=(
                self._parse_decimal(
                    raw_value=environment.get_ny_range_min_sl_pct(),
                    setting_name="NY_RANGE_MIN_SL_PCT",
                )
                if environment.get_ny_range_min_sl_pct()
                else Decimal("0.015")
            ),
            ny_range_fallback_sl_pct=(
                self._parse_decimal(
                    raw_value=environment.get_ny_range_fallback_sl_pct(),
                    setting_name="NY_RANGE_FALLBACK_SL_PCT",
                )
                if environment.get_ny_range_fallback_sl_pct()
                else Decimal("0.015")
            ),
            ny_range_max_breakout_bars=(
                self._parse_positive_int(
                    raw_value=environment.get_ny_range_max_breakout_bars(),
                    setting_name="NY_RANGE_MAX_BREAKOUT_BARS",
                )
                if environment.get_ny_range_max_breakout_bars()
                else 12
            ),
            ny_range_min_confidence=(
                self._parse_decimal(
                    raw_value=environment.get_ny_range_min_confidence(),
                    setting_name="NY_RANGE_MIN_CONFIDENCE",
                )
                if environment.get_ny_range_min_confidence()
                else Decimal("0.75")
            ),
            ny_range_base_confidence=(
                self._parse_decimal(
                    raw_value=environment.get_ny_range_base_confidence(),
                    setting_name="NY_RANGE_BASE_CONFIDENCE",
                )
                if environment.get_ny_range_base_confidence()
                else Decimal("0.70")
            ),
            ny_range_use_volume_filter=environment.get_ny_range_use_volume_filter(),
            ny_range_volume_period=(
                self._parse_positive_int(
                    raw_value=environment.get_ny_range_volume_period(),
                    setting_name="NY_RANGE_VOLUME_PERIOD",
                )
                if environment.get_ny_range_volume_period()
                else 20
            ),
            ny_range_volume_multiplier=(
                self._parse_decimal(
                    raw_value=environment.get_ny_range_volume_multiplier(),
                    setting_name="NY_RANGE_VOLUME_MULTIPLIER",
                )
                if environment.get_ny_range_volume_multiplier()
                else Decimal("1.0")
            ),
            ny_range_volume_confidence_bonus=(
                self._parse_decimal(
                    raw_value=environment.get_ny_range_volume_confidence_bonus(),
                    setting_name="NY_RANGE_VOLUME_CONFIDENCE_BONUS",
                )
                if environment.get_ny_range_volume_confidence_bonus()
                else Decimal("0.10")
            ),
            ny_range_require_volume_confirmation=(
                environment.get_ny_range_require_volume_confirmation()
            ),
            ny_range_require_trend_filter=(
                environment.get_ny_range_require_trend_filter()
            ),
            ny_range_trend_ema_period=(
                self._parse_positive_int(
                    raw_value=environment.get_ny_range_trend_ema_period(),
                    setting_name="NY_RANGE_TREND_EMA_PERIOD",
                )
                if environment.get_ny_range_trend_ema_period()
                else 50
            ),
            ny_range_use_rsi_filter=environment.get_ny_range_use_rsi_filter(),
            ny_range_rsi_period=(
                self._parse_positive_int(
                    raw_value=environment.get_ny_range_rsi_period(),
                    setting_name="NY_RANGE_RSI_PERIOD",
                )
                if environment.get_ny_range_rsi_period()
                else 14
            ),
            ny_range_rsi_long_max=(
                self._parse_decimal(
                    raw_value=environment.get_ny_range_rsi_long_max(),
                    setting_name="NY_RANGE_RSI_LONG_MAX",
                )
                if environment.get_ny_range_rsi_long_max()
                else Decimal("54.0")
            ),
            ny_range_rsi_short_min=(
                self._parse_decimal(
                    raw_value=environment.get_ny_range_rsi_short_min(),
                    setting_name="NY_RANGE_RSI_SHORT_MIN",
                )
                if environment.get_ny_range_rsi_short_min()
                else Decimal("44.0")
            ),
            origin_risk_reward_ratio=(
                self._parse_decimal(
                    raw_value=environment.get_origin_risk_reward_ratio(),
                    setting_name="ORIGIN_RISK_REWARD_RATIO",
                )
                if environment.get_origin_risk_reward_ratio()
                else Decimal("1.5")
            ),
            origin_min_sl_pct=(
                self._parse_decimal(
                    raw_value=environment.get_origin_min_sl_pct(),
                    setting_name="ORIGIN_MIN_SL_PCT",
                )
                if environment.get_origin_min_sl_pct()
                else Decimal("0.010")
            ),
            origin_max_sl_pct=(
                self._parse_decimal(
                    raw_value=environment.get_origin_max_sl_pct(),
                    setting_name="ORIGIN_MAX_SL_PCT",
                )
                if environment.get_origin_max_sl_pct()
                else Decimal("0.030")
            ),
            origin_fallback_sl_pct=(
                self._parse_decimal(
                    raw_value=environment.get_origin_fallback_sl_pct(),
                    setting_name="ORIGIN_FALLBACK_SL_PCT",
                )
                if environment.get_origin_fallback_sl_pct()
                else Decimal("0.015")
            ),
            origin_min_confidence=(
                self._parse_decimal(
                    raw_value=environment.get_origin_min_confidence(),
                    setting_name="ORIGIN_MIN_CONFIDENCE",
                )
                if environment.get_origin_min_confidence()
                else Decimal("0.70")
            ),
            origin_use_trend_filter=environment.get_origin_use_trend_filter(),
            origin_trend_ema_period=(
                self._parse_positive_int(
                    raw_value=environment.get_origin_trend_ema_period(),
                    setting_name="ORIGIN_TREND_EMA_PERIOD",
                )
                if environment.get_origin_trend_ema_period()
                else 50
            ),
            origin_use_volume_filter=environment.get_origin_use_volume_filter(),
            origin_volume_period=(
                self._parse_positive_int(
                    raw_value=environment.get_origin_volume_period(),
                    setting_name="ORIGIN_VOLUME_PERIOD",
                )
                if environment.get_origin_volume_period()
                else 20
            ),
            origin_volume_multiplier=(
                self._parse_decimal(
                    raw_value=environment.get_origin_volume_multiplier(),
                    setting_name="ORIGIN_VOLUME_MULTIPLIER",
                )
                if environment.get_origin_volume_multiplier()
                else Decimal("1.0")
            ),
            origin_use_rsi_filter=environment.get_origin_use_rsi_filter(),
            origin_rsi_period=(
                self._parse_positive_int(
                    raw_value=environment.get_origin_rsi_period(),
                    setting_name="ORIGIN_RSI_PERIOD",
                )
                if environment.get_origin_rsi_period()
                else 14
            ),
            origin_rsi_long_max=(
                self._parse_decimal(
                    raw_value=environment.get_origin_rsi_long_max(),
                    setting_name="ORIGIN_RSI_LONG_MAX",
                )
                if environment.get_origin_rsi_long_max()
                else Decimal("70.0")
            ),
            origin_rsi_short_min=(
                self._parse_decimal(
                    raw_value=environment.get_origin_rsi_short_min(),
                    setting_name="ORIGIN_RSI_SHORT_MIN",
                )
                if environment.get_origin_rsi_short_min()
                else Decimal("30.0")
            ),
            origin_require_rsi_direction=(
                environment.get_origin_require_rsi_direction()
            ),
            origin_use_bb_filter=environment.get_origin_use_bb_filter(),
            origin_bb_period=(
                self._parse_positive_int(
                    raw_value=environment.get_origin_bb_period(),
                    setting_name="ORIGIN_BB_PERIOD",
                )
                if environment.get_origin_bb_period()
                else 20
            ),
            origin_bb_std_dev=(
                self._parse_decimal(
                    raw_value=environment.get_origin_bb_std_dev(),
                    setting_name="ORIGIN_BB_STD_DEV",
                )
                if environment.get_origin_bb_std_dev()
                else Decimal("2.0")
            ),
            origin_use_macd_filter=environment.get_origin_use_macd_filter(),
            origin_macd_fast_period=(
                self._parse_positive_int(
                    raw_value=environment.get_origin_macd_fast_period(),
                    setting_name="ORIGIN_MACD_FAST_PERIOD",
                )
                if environment.get_origin_macd_fast_period()
                else 12
            ),
            origin_macd_slow_period=(
                self._parse_positive_int(
                    raw_value=environment.get_origin_macd_slow_period(),
                    setting_name="ORIGIN_MACD_SLOW_PERIOD",
                )
                if environment.get_origin_macd_slow_period()
                else 26
            ),
            origin_macd_signal_period=(
                self._parse_positive_int(
                    raw_value=environment.get_origin_macd_signal_period(),
                    setting_name="ORIGIN_MACD_SIGNAL_PERIOD",
                )
                if environment.get_origin_macd_signal_period()
                else 9
            ),
            origin_use_psar_filter=environment.get_origin_use_psar_filter(),
            origin_psar_max_proximity_pct=(
                self._parse_decimal(
                    raw_value=environment.get_origin_psar_max_proximity_pct(),
                    setting_name="ORIGIN_PSAR_MAX_PROXIMITY_PCT",
                )
                if environment.get_origin_psar_max_proximity_pct()
                else Decimal("0.008")
            ),
        )

    def load_logging_settings(
        self,
        *,
        app: AppSettings | None = None,
        exchange: ExchangeSettings | None = None,
    ) -> LoggingSettings:
        """Load logging settings from the environment with context scoping."""
        custom_filename = self._environment_provider.get_log_filename().strip()
        if custom_filename:
            filename = custom_filename
        elif app is not None and exchange is not None:
            filename = self.get_scoped_log_filename(app=app, exchange=exchange)
        else:
            filename = "botragram.log"

        return LoggingSettings(
            level=self._parse_enum(
                enum_type=LogLevel,
                raw_value=self._environment_provider.get_log_level(),
                setting_name="LOG_LEVEL",
            ),
            filename=filename,
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
            Interval,
            LogLevel,
            MarginMode,
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
    def _parse_market_interval(
        *,
        raw_value: str,
        setting_name: str = "GLOBAL_MARKET_INTERVAL",
    ) -> Interval:
        """Parse a case-sensitive candle interval.

        Raises:
            ValueError: If the configured interval is unsupported.
        """
        try:
            return Interval(raw_value)
        except ValueError as error:
            raise ValueError(
                f"Environment variable {setting_name!r} has invalid value {raw_value!r}"
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

    @classmethod
    def _parse_decimal_tuple(
        cls, *, raw_value: str, setting_name: str
    ) -> tuple[Decimal, ...]:
        """Parse comma-separated finite decimals into a tuple."""
        raw_parts = [part.strip() for part in raw_value.split(",") if part.strip()]
        if not raw_parts:
            raise ValueError(f"Environment variable {setting_name!r} cannot be empty")
        return tuple(
            cls._parse_decimal(raw_value=part, setting_name=setting_name)
            for part in raw_parts
        )

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

    @staticmethod
    def _parse_non_negative_float(*, raw_value: str, setting_name: str) -> float:
        """Parse one non-negative floating point configuration value."""
        try:
            value = float(raw_value)
        except ValueError as error:
            raise ValueError(
                f"Environment variable {setting_name!r} must be a number"
            ) from error

        if value < 0.0:
            raise ValueError(
                f"Environment variable {setting_name!r} must be non-negative"
            )

        return value
