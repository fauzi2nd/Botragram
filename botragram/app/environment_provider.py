"""
Botragram

Description:
    Environment variable loader and provider.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
import os
from pathlib import Path

# =============================================================================
# Third-Party Imports
# =============================================================================
from dotenv import dotenv_values, load_dotenv

from botragram.constants.env import (
    ENV_ACCOUNT_RATIO_HTF_PERIOD,
    ENV_ACTIVE_EXCHANGE,
    ENV_AI_MODEL,
    ENV_AI_PROVIDER,
    ENV_AUTONOMOUS_EXECUTION_ENABLED,
    ENV_AUTONOMOUS_LIVE_ENTRY_ENABLED,
    ENV_AUTONOMOUS_MAINNET_ENTRY_ENABLED,
    ENV_BASE_ASSET,
    ENV_BASELINE_CONFIDENCE,
    ENV_BASELINE_VOLATILITY_PCT,
    ENV_BINANCE_API_KEY,
    ENV_BINANCE_API_SECRET,
    ENV_BINANCE_MARKET_TYPE,
    ENV_BINANCE_TESTNET,
    ENV_BITGET_API_KEY,
    ENV_BITGET_API_SECRET,
    ENV_BITGET_CFD_MODE,
    ENV_BITGET_MARGIN_MODE,
    ENV_BITGET_MARKET_TYPE,
    ENV_BITGET_PASSPHRASE,
    ENV_BITGET_TESTNET,
    ENV_BOTRAGRAM_ENV_FILE,
    ENV_BOTRAGRAM_PROFILE,
    ENV_BREAKEVEN_FEE_BUFFER,
    ENV_BREAKEVEN_PROGRESS_THRESHOLD,
    ENV_BREAKEVEN_ROI_THRESHOLD,
    ENV_BTC_TREND_EMA_PERIOD,
    ENV_BTC_TREND_FILTER_ENABLED,
    ENV_BTC_TREND_INTERVAL,
    ENV_BYBIT_API_KEY,
    ENV_BYBIT_API_SECRET,
    ENV_BYBIT_DEMO,
    ENV_BYBIT_MARKET_TYPE,
    ENV_BYBIT_TESTNET,
    ENV_CANDLE_PRUNING_INTERVAL_HOURS,
    ENV_CANDLE_RETENTION_DAYS,
    ENV_CFD_QUOTE_ASSET,
    ENV_CFD_SYMBOL,
    ENV_CONFIDENCE_SIZING_ENABLED,
    ENV_CONFIRM_HTF_ACCOUNT_RATIO,
    ENV_DISCOVERY_BATCH_SIZE,
    ENV_DISCOVERY_CADENCE_SECONDS,
    ENV_DISCOVERY_CANDLE_DELAY_SECONDS,
    ENV_DISCOVERY_FILTER_EXTREME_VOLATILITY,
    ENV_DISCOVERY_FILTER_MIN_LIQUIDITY,
    ENV_DISCOVERY_MAX_CANDLE_VOLATILITY_PCT,
    ENV_DISCOVERY_MAX_UNIVERSE_SYMBOLS,
    ENV_DISCOVERY_MIN_24H_TURNOVER_USDT,
    ENV_DISCOVERY_MIN_QUOTE_VOLUME_USDT,
    ENV_DISCOVERY_UNIVERSE_LIMIT,
    ENV_DISCOVERY_USE_DYNAMIC_VOLUME,
    ENV_DISCOVERY_VOLUME_SMA_PERIOD,
    ENV_DYNAMIC_LEVERAGE_ENABLED,
    ENV_DYNAMIC_SIZING_ENABLED,
    ENV_EARLY_EXIT_CHECK_CANDLESTICK_REVERSAL,
    ENV_EARLY_EXIT_CHECK_EXHAUSTION,
    ENV_EARLY_EXIT_CHECK_OPPOSITE_SIGNAL,
    ENV_EARLY_EXIT_MIN_CONFIDENCE,
    ENV_EMA_CROSS_STOP_LOSS_PCT,
    ENV_EMA_CROSS_TAKE_PROFIT_PCT,
    ENV_EMA_SCALPING_STOP_LOSS_PCT,
    ENV_EMA_SCALPING_TAKE_PROFIT_PCT,
    ENV_ENABLE_EARLY_POSITION_EXIT,
    ENV_EXCHANGE_API_KEY_LEGACY,
    ENV_EXCHANGE_API_SECRET_LEGACY,
    ENV_EXECUTION_POLICY,
    ENV_FILTER_ACCOUNT_RATIO,
    ENV_FILTER_FUNDING_SENTIMENT,
    ENV_FUTURES_QUOTE_ASSET,
    ENV_FUTURES_SYMBOL,
    ENV_GEMINI_API_KEY,
    ENV_GLOBAL_MARKET_INTERVAL,
    ENV_INVERT_SIGNALS,
    ENV_LEVERAGE,
    ENV_LOG_FILENAME,
    ENV_LOG_LEVEL,
    ENV_LOG_LEVEL_LEGACY,
    ENV_LTF_CONFIRMATION_ENABLED,
    ENV_LTF_CONFIRMATION_MODE,
    ENV_LTF_EMA_PERIOD,
    ENV_LTF_TIMEFRAME,
    ENV_MARGIN_MODE,
    ENV_MARKET_INTERVAL,
    ENV_MARKET_SYMBOL,
    ENV_MAX_CONFIDENCE_MULTIPLIER,
    ENV_MAX_DRAWDOWN_PCT,
    ENV_MAX_EXECUTABLE_QUOTE_AGE_MS,
    ENV_MAX_LEVERAGE,
    ENV_MAX_LONG_ACCOUNT_RATIO,
    ENV_MAX_LONG_FUNDING_RATE,
    ENV_MAX_OPEN_POSITIONS,
    ENV_MAX_POSITION_SIZE_USDT,
    ENV_MAX_SPREAD_BPS,
    ENV_MIN_LEVERAGE,
    ENV_MIN_OI_CHANGE_PCT,
    ENV_MIN_ORDER_NOTIONAL_USDT,
    ENV_MIN_SHORT_ACCOUNT_RATIO,
    ENV_MIN_SHORT_FUNDING_RATE,
    ENV_MIN_SIGNAL_CONFIDENCE,
    ENV_MTF_CONFIRMATION_ENABLED,
    ENV_MTF_EMA_PERIOD,
    ENV_MTF_TIMEFRAME,
    ENV_NY_RANGE_BASE_CONFIDENCE,
    ENV_NY_RANGE_FALLBACK_SL_PCT,
    ENV_NY_RANGE_MAX_BREAKOUT_BARS,
    ENV_NY_RANGE_MAX_SL_PCT,
    ENV_NY_RANGE_MIN_CONFIDENCE,
    ENV_NY_RANGE_MIN_SL_PCT,
    ENV_NY_RANGE_REQUIRE_TREND_FILTER,
    ENV_NY_RANGE_REQUIRE_VOLUME_CONFIRMATION,
    ENV_NY_RANGE_RISK_REWARD_RATIO,
    ENV_NY_RANGE_RSI_LONG_MAX,
    ENV_NY_RANGE_RSI_PERIOD,
    ENV_NY_RANGE_RSI_SHORT_MIN,
    ENV_NY_RANGE_TREND_EMA_PERIOD,
    ENV_NY_RANGE_USE_RSI_FILTER,
    ENV_NY_RANGE_USE_VOLUME_FILTER,
    ENV_NY_RANGE_VOLUME_CONFIDENCE_BONUS,
    ENV_NY_RANGE_VOLUME_MULTIPLIER,
    ENV_NY_RANGE_VOLUME_PERIOD,
    ENV_OKX_API_KEY,
    ENV_OKX_API_SECRET,
    ENV_OKX_PASSPHRASE,
    ENV_OKX_TESTNET,
    ENV_OPENAI_API_KEY,
    ENV_OPENROUTER_API_KEY,
    ENV_ORIGIN_BB_PERIOD,
    ENV_ORIGIN_BB_STD_DEV,
    ENV_ORIGIN_FALLBACK_SL_PCT,
    ENV_ORIGIN_MACD_FAST_PERIOD,
    ENV_ORIGIN_MACD_SIGNAL_PERIOD,
    ENV_ORIGIN_MACD_SLOW_PERIOD,
    ENV_ORIGIN_MAX_SL_PCT,
    ENV_ORIGIN_MIN_CONFIDENCE,
    ENV_ORIGIN_MIN_SL_PCT,
    ENV_ORIGIN_PSAR_MAX_PROXIMITY_PCT,
    ENV_ORIGIN_REQUIRE_RSI_DIRECTION,
    ENV_ORIGIN_RISK_REWARD_RATIO,
    ENV_ORIGIN_RSI_LONG_MAX,
    ENV_ORIGIN_RSI_PERIOD,
    ENV_ORIGIN_RSI_SHORT_MIN,
    ENV_ORIGIN_STOP_LOSS_PCT,
    ENV_ORIGIN_TAKE_PROFIT_PCT,
    ENV_ORIGIN_TREND_EMA_PERIOD,
    ENV_ORIGIN_USE_BB_FILTER,
    ENV_ORIGIN_USE_MACD_FILTER,
    ENV_ORIGIN_USE_PSAR_FILTER,
    ENV_ORIGIN_USE_RSI_FILTER,
    ENV_ORIGIN_USE_TREND_FILTER,
    ENV_ORIGIN_USE_VOLUME_FILTER,
    ENV_ORIGIN_VOLUME_MULTIPLIER,
    ENV_ORIGIN_VOLUME_PERIOD,
    ENV_PARTIAL_TP_ENABLED,
    ENV_PARTIAL_TP_RATIO,
    ENV_PARTIAL_TP_TRIGGER_PROGRESS,
    ENV_PIER_ATR_PERIOD,
    ENV_PIER_ATR_SL_MULTIPLIER,
    ENV_PIER_BB_PERIOD,
    ENV_PIER_BB_STD_DEV,
    ENV_PIER_CONFIRM_HTF_ACCOUNT_RATIO,
    ENV_PIER_EARLY_EXIT_CHECK_CANDLESTICK_REVERSAL,
    ENV_PIER_EARLY_EXIT_CHECK_EXHAUSTION,
    ENV_PIER_EARLY_EXIT_CHECK_OPPOSITE_SIGNAL,
    ENV_PIER_EARLY_EXIT_MIN_CONFIDENCE,
    ENV_PIER_ENABLE_EARLY_POSITION_EXIT,
    ENV_PIER_ENGULFING_MIN_BODY_ATR,
    ENV_PIER_FILTER_ACCOUNT_RATIO,
    ENV_PIER_HTF_BB_PERIOD,
    ENV_PIER_HTF_BB_STD_DEV,
    ENV_PIER_HTF_INTERVAL,
    ENV_PIER_INCLUDE_STAR_PATTERNS,
    ENV_PIER_LEVERAGE,
    ENV_PIER_LOCATION_ATR_MULTIPLIER,
    ENV_PIER_LOCATION_TOLERANCE_PCT,
    ENV_PIER_MACD_FAST_PERIOD,
    ENV_PIER_MACD_SIGNAL_PERIOD,
    ENV_PIER_MACD_SLOW_PERIOD,
    ENV_PIER_MAX_LONG_ACCOUNT_RATIO,
    ENV_PIER_MAX_OPPOSITE_WICK_RATIO,
    ENV_PIER_MAX_POSITION_SIZE_USDT,
    ENV_PIER_MIN_CONFIDENCE,
    ENV_PIER_MIN_ENGULFING_BODY_RATIO,
    ENV_PIER_MIN_NATR_THRESHOLD,
    ENV_PIER_MIN_OI_CHANGE_PCT,
    ENV_PIER_MIN_SHORT_ACCOUNT_RATIO,
    ENV_PIER_MIN_SL_DISTANCE_PCT,
    ENV_PIER_MIN_STRUCTURAL_RR,
    ENV_PIER_MIN_WICK_RATIO,
    ENV_PIER_OI_CONFIDENCE_BONUS,
    ENV_PIER_PARTIAL_TP_ENABLED,
    ENV_PIER_PARTIAL_TP_RATIO,
    ENV_PIER_PARTIAL_TP_TRIGGER_PROGRESS,
    ENV_PIER_PINBAR_MIN_RANGE_ATR,
    ENV_PIER_PULLBACK_ATR_MULTIPLIER,
    ENV_PIER_PULLBACK_PERIOD,
    ENV_PIER_PULLBACK_PROXIMITY_PCT,
    ENV_PIER_REQUIRE_ACCOUNT_RATIO_CONFLUENCE,
    ENV_PIER_REQUIRE_CONFIRMATION,
    ENV_PIER_REQUIRE_KEY_LEVEL_LOCATION,
    ENV_PIER_REQUIRE_OI_CONFLUENCE,
    ENV_PIER_REQUIRE_TREND_FILTER,
    ENV_PIER_RISK_PER_TRADE_PCT,
    ENV_PIER_RISK_REWARD_RATIO,
    ENV_PIER_RSI_LONG_MAX,
    ENV_PIER_RSI_LONG_MIN,
    ENV_PIER_RSI_PERIOD,
    ENV_PIER_RSI_SHORT_MAX,
    ENV_PIER_RSI_SHORT_MIN,
    ENV_PIER_STOCH_RSI_D_PERIOD,
    ENV_PIER_STOCH_RSI_K_PERIOD,
    ENV_PIER_STOCH_RSI_OVERBOUGHT,
    ENV_PIER_STOCH_RSI_OVERSOLD,
    ENV_PIER_STOCH_RSI_PERIOD,
    ENV_PIER_STOP_LOSS_PCT,
    ENV_PIER_STRUCTURAL_TP_BUFFER_PCT,
    ENV_PIER_SWING_LOOKBACK,
    ENV_PIER_TAKE_PROFIT_PCT,
    ENV_PIER_TRAILING_BUFFER_PCT,
    ENV_PIER_TRAILING_MODE,
    ENV_PIER_TRAILING_SWING_TIMEFRAME,
    ENV_PIER_TRAILING_SWING_WINDOW,
    ENV_PIER_TREND_PERIOD,
    ENV_PIER_USE_HTF_STRUCTURAL_TP,
    ENV_PIER_USE_MACD,
    ENV_PIER_USE_OPEN_INTEREST,
    ENV_PIER_USE_PARABOLIC_SAR,
    ENV_PIER_USE_STOCH_RSI,
    ENV_PIER_USE_STRUCTURAL_TP,
    ENV_PIER_VOLUME_MULTIPLIER,
    ENV_PIER_VOLUME_PERIOD,
    ENV_QUOTE_ASSET,
    ENV_REQUIRE_ACCOUNT_RATIO_CONFLUENCE,
    ENV_REQUIRE_FUNDING_SENTIMENT,
    ENV_REQUIRE_OI_CONFLUENCE,
    ENV_RISK_PER_TRADE_PCT,
    ENV_SCALPING_STOP_LOSS_PCT,
    ENV_SCALPING_TAKE_PROFIT_PCT,
    ENV_SLOT_MARGIN_BUFFER_PCT,
    ENV_SLOT_SIZING_ENABLED,
    ENV_SPOT_SYMBOL,
    ENV_STEPPED_STOP_ENABLED,
    ENV_STEPPED_STOP_LOCKED_LAG,
    ENV_STEPPED_STOP_THRESHOLDS,
    ENV_STOP_LOSS_PCT,
    ENV_STRATEGY_TIMEFRAME_OVERRIDE,
    ENV_STRATEGY_TIMEFRAME_OVERRIDE_ENABLED,
    ENV_STRATEGY_TYPE,
    ENV_SWING_STOP_LOSS_PCT,
    ENV_SWING_TAKE_PROFIT_PCT,
    ENV_SYMBOL,
    ENV_TAKE_PROFIT_PCT,
    ENV_TELEGRAM_CHAT_ID,
    ENV_TELEGRAM_TOKEN,
    ENV_TELEGRAM_TOKEN_LEGACY,
    ENV_TRADE_MODE,
    ENV_TRADE_MODE_LEGACY,
    ENV_TRAILING_BUFFER_PCT,
    ENV_TRAILING_MODE,
    ENV_TRAILING_SWING_TIMEFRAME,
    ENV_TRAILING_SWING_WINDOW,
    ENV_TREND_STOP_LOSS_PCT,
    ENV_TREND_TAKE_PROFIT_PCT,
    ENV_USE_OPEN_INTEREST,
    ENV_VOLATILITY_SIZING_ENABLED,
)

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import EnvironmentProfile, StrategyType

__all__ = [
    "EnvironmentProvider",
]


# =============================================================================
# Constants
# =============================================================================
_TRUE_VALUES = frozenset(
    {
        "1",
        "true",
        "yes",
        "on",
    }
)

_FALSE_VALUES = frozenset(
    {
        "0",
        "false",
        "no",
        "off",
    }
)

_PROFILE_REQUIRED_KEYS = frozenset(
    {
        ENV_BINANCE_API_KEY,
        ENV_BINANCE_API_SECRET,
        ENV_BINANCE_TESTNET,
    }
)


# =============================================================================
# Environment Provider
# =============================================================================
class EnvironmentProvider:
    """Provide normalized access to Botragram environment variables."""

    __slots__ = (
        "_env_path",
        "_profile",
        "_profile_path",
    )

    def __init__(
        self,
        env_path: str | None = None,
        *,
        override: bool = True,
    ) -> None:
        """Load environment variables from a dotenv file.

        Args:
            env_path: Path to the dotenv file. When omitted, the explicit
                BOTRAGRAM_ENV_FILE bootstrap value selects a file; otherwise
                the default remains .env.
            override: Whether dotenv values override inherited process
                variables. Enabled by default so local configuration is
                deterministic.
        """
        normalized_path = self._resolve_env_path(env_path=env_path)

        if not normalized_path:
            raise ValueError("Environment file path must not be empty")

        self._env_path = normalized_path
        self._profile: EnvironmentProfile | None = None
        self._profile_path: str | None = None

        load_dotenv(
            dotenv_path=self._env_path,
            override=override,
        )
        self._load_environment_profile()

    @staticmethod
    def _resolve_env_path(*, env_path: str | None) -> str:
        """Resolve the base dotenv path before loading any dotenv values."""
        if env_path is not None:
            return env_path.strip()

        selected_path = os.getenv(ENV_BOTRAGRAM_ENV_FILE, "").strip()
        if not selected_path:
            return ".env"

        if not Path(selected_path).is_file():
            raise FileNotFoundError(
                f"Explicit environment file does not exist: {selected_path}"
            )

        return selected_path

    @property
    def env_path(self) -> str:
        """Return the configured dotenv file path."""
        return self._env_path

    @property
    def profile(self) -> EnvironmentProfile | None:
        """Return the selected credential environment profile."""
        return self._profile

    @property
    def profile_path(self) -> str | None:
        """Return the selected credential profile path."""
        return self._profile_path

    @staticmethod
    def _get_var(
        primary_key: str,
        fallback_key: str | None = None,
        *,
        default: str = "",
    ) -> str:
        """Return a stripped environment value with optional fallback."""
        primary_value = os.getenv(primary_key)

        if primary_value is not None:
            normalized_primary = primary_value.strip()

            if normalized_primary.startswith("#"):
                normalized_primary = ""

            if normalized_primary:
                return normalized_primary

        if fallback_key is not None:
            fallback_value = os.getenv(fallback_key)

            if fallback_value is not None:
                normalized_fallback = fallback_value.strip()

                if normalized_fallback.startswith("#"):
                    normalized_fallback = ""

                if normalized_fallback:
                    return normalized_fallback

        return default

    @classmethod
    def _get_bool(
        cls,
        key: str,
        *,
        default: bool,
    ) -> bool:
        """Return a strict boolean environment value.

        Raises:
            ValueError: If a configured value is not a recognized boolean.
        """
        raw_value = cls._get_var(key)

        if not raw_value:
            return default

        return cls._parse_bool_value(
            key=key,
            raw_value=raw_value,
        )

    @staticmethod
    def _parse_bool_value(
        *,
        key: str,
        raw_value: str,
    ) -> bool:
        """Parse a strict boolean environment value."""
        normalized = raw_value.strip().casefold()

        if normalized in _TRUE_VALUES:
            return True

        if normalized in _FALSE_VALUES:
            return False

        raise ValueError(
            f"Environment variable {key!r} must be one of "
            f"{sorted(_TRUE_VALUES | _FALSE_VALUES)!r}, "
            f"not {raw_value!r}"
        )

    def _load_environment_profile(self) -> None:
        """Load and validate an explicitly selected credential profile."""
        raw_profile = self._get_var(ENV_BOTRAGRAM_PROFILE)

        if not raw_profile:
            return

        profile = self._parse_profile(raw_profile)
        profile_path = self._build_profile_path(profile)
        profile_values = self._read_profile_values(profile_path)
        self._validate_profile_network(
            profile=profile,
            profile_values=profile_values,
        )
        load_dotenv(
            dotenv_path=profile_path,
            override=True,
        )
        self._profile = profile
        self._profile_path = str(profile_path)

    @staticmethod
    def _parse_profile(raw_profile: str) -> EnvironmentProfile:
        """Parse a supported credential environment profile."""
        try:
            return EnvironmentProfile(raw_profile.casefold())
        except ValueError as error:
            supported = tuple(profile.value for profile in EnvironmentProfile)
            raise ValueError(
                f"Environment variable {ENV_BOTRAGRAM_PROFILE!r} must be one "
                f"of {supported!r}, not {raw_profile!r}"
            ) from error

    def _build_profile_path(self, profile: EnvironmentProfile) -> Path:
        """Build the credential profile path beside the base dotenv file."""
        base_path = Path(self._env_path)
        profile_path = base_path.with_name(f"{base_path.name}.{profile.value}")
        if not profile_path.is_file() and base_path.name != ".env":
            root_profile_path = base_path.with_name(f".env.{profile.value}")
            if root_profile_path.is_file():
                return root_profile_path
        return profile_path

    @staticmethod
    def _read_profile_values(profile_path: Path) -> dict[str, str | None]:
        """Read a credential profile and require its safety fields."""
        if not profile_path.is_file():
            raise FileNotFoundError(
                f"Credential environment profile does not exist: {profile_path}"
            )

        values = dict(dotenv_values(profile_path))
        missing_keys = sorted(_PROFILE_REQUIRED_KEYS - values.keys())

        if missing_keys:
            raise ValueError(
                f"Credential environment profile {profile_path} is missing "
                f"required keys: {missing_keys!r}"
            )

        return values

    @classmethod
    def _validate_profile_network(
        cls,
        *,
        profile: EnvironmentProfile,
        profile_values: dict[str, str | None],
    ) -> None:
        """Require the selected profile to match its Binance network flag."""
        raw_testnet = profile_values[ENV_BINANCE_TESTNET]

        if raw_testnet is None:
            raise ValueError(
                f"Environment variable {ENV_BINANCE_TESTNET!r} must not be empty"
            )

        is_testnet = cls._parse_bool_value(
            key=ENV_BINANCE_TESTNET,
            raw_value=raw_testnet,
        )
        expected_testnet = profile is EnvironmentProfile.TESTNET

        if is_testnet is not expected_testnet:
            raise ValueError(
                f"Credential profile {profile.value!r} requires "
                f"{ENV_BINANCE_TESTNET}={str(expected_testnet).lower()}"
            )

    # -------------------------------------------------------------------------
    # AI
    # -------------------------------------------------------------------------

    def get_openai_api_key(self) -> str:
        """Return the OpenAI API key."""
        return self._get_var(ENV_OPENAI_API_KEY)

    def get_gemini_api_key(self) -> str:
        """Return the Gemini API key."""
        return self._get_var(ENV_GEMINI_API_KEY)

    def get_openrouter_api_key(self) -> str:
        """Return the OpenRouter API key."""
        return self._get_var(ENV_OPENROUTER_API_KEY)

    def get_ai_provider(self) -> str:
        """Return the configured AI provider name."""
        return self._get_var(
            ENV_AI_PROVIDER,
            default="OPENAI",
        ).upper()

    def get_ai_model(self) -> str:
        """Return the configured AI model name."""
        return self._get_var(ENV_AI_MODEL)

    # -------------------------------------------------------------------------
    # Telegram
    # -------------------------------------------------------------------------

    def get_telegram_token(self) -> str:
        """Return the Telegram bot token."""
        return self._get_var(
            ENV_TELEGRAM_TOKEN,
            ENV_TELEGRAM_TOKEN_LEGACY,
        )

    def get_telegram_chat_id(self) -> str:
        """Return the Telegram chat identifier."""
        return self._get_var(ENV_TELEGRAM_CHAT_ID)

    def get_bot_token(self) -> str:
        """Return the Telegram bot token.

        This alias is retained for backward compatibility.
        """
        return self.get_telegram_token()

    def get_chat_id(self) -> str:
        """Return the Telegram chat identifier.

        This alias is retained for backward compatibility.
        """
        return self.get_telegram_chat_id()

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------

    def get_trade_mode(self) -> str:
        """Return the configured trade execution mode."""
        return self._get_var(
            ENV_TRADE_MODE,
            ENV_TRADE_MODE_LEGACY,
            default="PAPER",
        ).upper()

    def get_log_level(self) -> str:
        """Return the configured logging level."""
        return self._get_var(
            ENV_LOG_LEVEL,
            ENV_LOG_LEVEL_LEGACY,
            default="INFO",
        ).upper()

    def get_log_filename(self) -> str:
        """Return the optional explicit log filename."""
        return self._get_var(ENV_LOG_FILENAME)

    def get_autonomous_execution_enabled(self) -> bool:
        """Return whether autonomous opportunity execution is enabled."""
        return self._get_bool(ENV_AUTONOMOUS_EXECUTION_ENABLED, default=False)

    def get_autonomous_live_entry_enabled(self) -> bool:
        """Return the base explicit opt-in for autonomous LIVE entry."""
        return self._get_bool(ENV_AUTONOMOUS_LIVE_ENTRY_ENABLED, default=False)

    def get_autonomous_mainnet_entry_enabled(self) -> bool:
        """Return the additional explicit opt-in for MAINNET autonomous entry."""
        return self._get_bool(ENV_AUTONOMOUS_MAINNET_ENTRY_ENABLED, default=False)

    def get_execution_policy(self) -> str:
        """Return the optional explicit runtime execution policy."""
        return self._get_var(ENV_EXECUTION_POLICY)

    def get_strategy_type(self) -> str:
        """Return the optional configured trading strategy type."""
        return self._get_var(ENV_STRATEGY_TYPE)

    def get_invert_signals(self) -> bool:
        """Return whether strategy signals should be inverted."""
        return self._get_bool(ENV_INVERT_SIGNALS, default=False)

    def get_min_signal_confidence(self) -> str:
        """Return the minimum signal confidence threshold for entry."""
        return self._get_var(ENV_MIN_SIGNAL_CONFIDENCE, default="0.0")

    def get_mtf_confirmation_enabled(self) -> bool:
        """Return whether multi-timeframe trend confirmation is enabled."""
        return self._get_bool(ENV_MTF_CONFIRMATION_ENABLED, default=False)

    def get_mtf_interval(self) -> str:
        """Return the higher timeframe for MTF trend confirmation."""
        return self._get_var(ENV_MTF_TIMEFRAME, default="1h")

    def get_mtf_ema_period(self) -> str:
        """Return the lookback period for MTF trend EMA."""
        return self._get_var(ENV_MTF_EMA_PERIOD, default="50")

    def get_ltf_confirmation_enabled(self) -> bool:
        """Return whether low-timeframe micro-confirmation is enabled."""
        return self._get_bool(ENV_LTF_CONFIRMATION_ENABLED, default=False)

    def get_ltf_interval(self) -> str:
        """Return the micro timeframe for LTF confirmation."""
        return self._get_var(ENV_LTF_TIMEFRAME, default="3m")

    def get_ltf_confirmation_mode(self) -> str:
        """Return the evaluation mode for LTF micro-confirmation."""
        return self._get_var(ENV_LTF_CONFIRMATION_MODE, default="direction")

    def get_ltf_ema_period(self) -> str:
        """Return the lookback period for LTF trend EMA."""
        return self._get_var(ENV_LTF_EMA_PERIOD, default="9")

    def get_btc_trend_filter_enabled(self) -> bool:
        """Return whether BTC benchmark trend filter is enabled."""
        return self._get_bool(ENV_BTC_TREND_FILTER_ENABLED, default=True)

    def get_btc_trend_interval(self) -> str:
        """Return the timeframe for BTC benchmark trend filter."""
        return self._get_var(ENV_BTC_TREND_INTERVAL, default="15m")

    def get_btc_trend_ema_period(self) -> str:
        """Return the lookback period for BTC benchmark trend EMA."""
        return self._get_var(ENV_BTC_TREND_EMA_PERIOD, default="50")

    def get_discovery_filter_extreme_volatility(self) -> bool:
        """Return whether extreme volatility filter is enabled in discovery."""
        return self._get_bool(ENV_DISCOVERY_FILTER_EXTREME_VOLATILITY, default=True)

    def get_discovery_max_candle_volatility_pct(self) -> str:
        """Return max candle volatility threshold percentage for discovery."""
        return self._get_var(ENV_DISCOVERY_MAX_CANDLE_VOLATILITY_PCT, default="0.15")

    def get_discovery_filter_min_liquidity(self) -> bool:
        """Return whether minimum liquidity filter is enabled in discovery."""
        return self._get_bool(ENV_DISCOVERY_FILTER_MIN_LIQUIDITY, default=True)

    def get_discovery_min_quote_volume_usdt(self) -> str:
        """Return minimum quote volume in USDT for discovery filtering."""
        return self._get_var(ENV_DISCOVERY_MIN_QUOTE_VOLUME_USDT, default="1000")

    def get_discovery_use_dynamic_volume(self) -> bool:
        """Return whether dynamic volume filtering is enabled in discovery."""
        return self._get_bool(ENV_DISCOVERY_USE_DYNAMIC_VOLUME, default=True)

    def get_discovery_volume_sma_period(self) -> str:
        """Return rolling SMA period for discovery volume estimation."""
        return self._get_var(ENV_DISCOVERY_VOLUME_SMA_PERIOD, default="20")

    def get_discovery_min_24h_turnover_usdt(self) -> str:
        """Return minimum 24-hour estimated turnover in USDT for discovery."""
        return self._get_var(ENV_DISCOVERY_MIN_24H_TURNOVER_USDT, default="1000000")

    def get_use_open_interest(self) -> bool:
        """Return whether Open Interest confluence evaluation is enabled."""
        return self._get_bool(ENV_USE_OPEN_INTEREST, default=False)

    def get_min_oi_change_pct(self) -> str:
        """Return the minimum Open Interest percentage change for confirmation."""
        return self._get_var(ENV_MIN_OI_CHANGE_PCT, default="0.0")

    def get_require_oi_confluence(self) -> bool:
        """Return whether strict Open Interest confluence is required."""
        return self._get_bool(ENV_REQUIRE_OI_CONFLUENCE, default=False)

    def get_filter_funding_sentiment(self) -> bool:
        """Return whether Funding Rate crowding sentiment filter is enabled."""
        return self._get_bool(ENV_FILTER_FUNDING_SENTIMENT, default=True)

    def get_max_long_funding_rate(self) -> str:
        """Return the maximum funding rate allowed for BUY signals."""
        return self._get_var(ENV_MAX_LONG_FUNDING_RATE, default="0.0005")

    def get_min_short_funding_rate(self) -> str:
        """Return the minimum funding rate allowed for SELL signals."""
        return self._get_var(ENV_MIN_SHORT_FUNDING_RATE, default="-0.0005")

    def get_require_funding_sentiment(self) -> bool:
        """Return whether crowded funding rate strictly forces HOLD."""
        return self._get_bool(ENV_REQUIRE_FUNDING_SENTIMENT, default=True)

    def get_filter_account_ratio(self) -> bool:
        """Return whether Account Long-Short Ratio sentiment filter is enabled."""
        return self._get_bool(ENV_FILTER_ACCOUNT_RATIO, default=True)

    def get_max_long_account_ratio(self) -> str:
        """Return the maximum long account ratio allowed for BUY signals."""
        return self._get_var(ENV_MAX_LONG_ACCOUNT_RATIO, default="0.75")

    def get_min_short_account_ratio(self) -> str:
        """Return the minimum long account ratio allowed for SELL signals."""
        return self._get_var(ENV_MIN_SHORT_ACCOUNT_RATIO, default="0.25")

    def get_require_account_ratio_confluence(self) -> bool:
        """Return whether crowded account ratio strictly forces HOLD."""
        return self._get_bool(ENV_REQUIRE_ACCOUNT_RATIO_CONFLUENCE, default=True)

    def get_confirm_htf_account_ratio(self) -> bool:
        """Return whether higher timeframe account ratio confirmation is enabled."""
        return self._get_bool(ENV_CONFIRM_HTF_ACCOUNT_RATIO, default=False)

    def get_account_ratio_htf_period(self) -> str:
        """Return the higher timeframe period for account ratio confirmation."""
        return self._get_var(ENV_ACCOUNT_RATIO_HTF_PERIOD, default="1h")

    def get_breakeven_roi_threshold(self) -> str:
        """Return the minimum ROI threshold to arm breakeven protection."""
        return self._get_var(ENV_BREAKEVEN_ROI_THRESHOLD, default="0.30")

    def get_breakeven_progress_threshold(self) -> str:
        """Return the minimum TP progress threshold to arm breakeven protection."""
        return self._get_var(ENV_BREAKEVEN_PROGRESS_THRESHOLD, default="0.35")

    def get_breakeven_fee_buffer(self) -> str:
        """Return the fee buffer fraction added to entry price at breakeven."""
        return self._get_var(ENV_BREAKEVEN_FEE_BUFFER, default="0.0016")

    def get_stepped_stop_enabled(self) -> bool:
        """Return whether stepped stop loss (SL+ profit lock) is enabled."""
        return self._get_bool(ENV_STEPPED_STOP_ENABLED, default=True)

    def get_stepped_stop_thresholds(self) -> str:
        """Return comma-separated TP progress thresholds for stepped stop loss."""
        return self._get_var(
            ENV_STEPPED_STOP_THRESHOLDS, default="0.30,0.45,0.60,0.75,0.90"
        )

    def get_stepped_stop_locked_lag(self) -> str:
        """Return the locked profit lag behind the current reached step."""
        return self._get_var(ENV_STEPPED_STOP_LOCKED_LAG, default="0.20")

    def get_trailing_mode(self) -> str:
        """Return the trailing stop protection mode."""
        return self._get_var(ENV_TRAILING_MODE, default="swing_pivot")

    def get_trailing_swing_timeframe(self) -> str:
        """Return the timeframe for trailing swing pivot tracking."""
        return self._get_var(ENV_TRAILING_SWING_TIMEFRAME, default="5m")

    def get_trailing_swing_window(self) -> str:
        """Return the window size for trailing swing pivot tracking."""
        return self._get_var(ENV_TRAILING_SWING_WINDOW, default="5")

    def get_trailing_buffer_pct(self) -> str:
        """Return the buffer percentage below swing low or above swing high."""
        return self._get_var(ENV_TRAILING_BUFFER_PCT, default="0.0015")

    def get_partial_tp_enabled(self) -> bool:
        """Return whether partial take profit is enabled."""
        return self._get_bool(ENV_PARTIAL_TP_ENABLED, default=False)

    def get_partial_tp_ratio(self) -> str:
        """Return the fraction of position to close at partial take profit."""
        return self._get_var(ENV_PARTIAL_TP_RATIO, default="0.50")

    def get_partial_tp_trigger_progress(self) -> str:
        """Return the TP progress threshold that triggers partial close."""
        return self._get_var(ENV_PARTIAL_TP_TRIGGER_PROGRESS, default="0.50")

    def get_enable_early_position_exit(self) -> bool:
        """Return whether early in-flight position exit monitoring is enabled."""
        return self._get_bool(ENV_ENABLE_EARLY_POSITION_EXIT, default=False)

    def get_early_exit_min_confidence(self) -> str:
        """Return the minimum confidence threshold for early position exit."""
        return self._get_var(ENV_EARLY_EXIT_MIN_CONFIDENCE, default="0.75")

    def get_early_exit_check_candlestick_reversal(self) -> bool:
        """Return whether candlestick reversal patterns trigger early exit."""
        return self._get_bool(ENV_EARLY_EXIT_CHECK_CANDLESTICK_REVERSAL, default=True)

    def get_early_exit_check_opposite_signal(self) -> bool:
        """Return whether confirmed opposite signals trigger early exit."""
        return self._get_bool(ENV_EARLY_EXIT_CHECK_OPPOSITE_SIGNAL, default=True)

    def get_early_exit_check_exhaustion(self) -> bool:
        """Return whether multi-indicator exhaustion confluence triggers early exit."""
        return self._get_bool(ENV_EARLY_EXIT_CHECK_EXHAUSTION, default=True)

    def get_volatility_sizing_enabled(self) -> bool:
        """Return whether volatility-adjusted sizing is enabled."""
        return self._get_bool(ENV_VOLATILITY_SIZING_ENABLED, default=False)

    def get_baseline_volatility_pct(self) -> str:
        """Return the baseline volatility percentage for sizing."""
        return self._get_var(ENV_BASELINE_VOLATILITY_PCT, default="0.02")

    def get_dynamic_sizing_enabled(self) -> bool:
        """Return whether dynamic position sizing is enabled."""
        return self._get_bool(ENV_DYNAMIC_SIZING_ENABLED, default=False)

    def get_confidence_sizing_enabled(self) -> bool:
        """Return whether confidence-weighted sizing is enabled."""
        return self._get_bool(ENV_CONFIDENCE_SIZING_ENABLED, default=True)

    def get_baseline_confidence(self) -> str:
        """Return baseline confidence for dynamic scaling."""
        return self._get_var(ENV_BASELINE_CONFIDENCE, default="0.70")

    def get_max_confidence_multiplier(self) -> str:
        """Return max multiplier for high-confidence signals."""
        return self._get_var(ENV_MAX_CONFIDENCE_MULTIPLIER, default="1.5")

    def get_dynamic_leverage_enabled(self) -> bool:
        """Return whether adaptive safe leverage is enabled."""
        return self._get_bool(ENV_DYNAMIC_LEVERAGE_ENABLED, default=False)

    def get_min_leverage(self) -> str:
        """Return minimum bound for adaptive leverage."""
        return self._get_var(ENV_MIN_LEVERAGE, default="5")

    def get_max_leverage(self) -> str:
        """Return maximum bound for adaptive leverage."""
        return self._get_var(ENV_MAX_LEVERAGE, default="25")

    def get_slot_sizing_enabled(self) -> bool:
        """Return whether dynamic slot-based margin allocation is enabled."""
        return self._get_bool(ENV_SLOT_SIZING_ENABLED, default=False)

    def get_slot_margin_buffer_pct(self) -> str:
        """Return the reserve safety buffer percentage for slot margin."""
        return self._get_var(ENV_SLOT_MARGIN_BUFFER_PCT, default="0.05")

    def get_min_order_notional_usdt(self) -> str:
        """Return the minimum exchange order notional threshold."""
        return self._get_var(ENV_MIN_ORDER_NOTIONAL_USDT, default="5.0")

    def get_scalping_stop_loss_pct(self) -> str:
        """Return the scalping stop-loss ratio."""
        return self._get_var(
            ENV_SCALPING_STOP_LOSS_PCT,
            ENV_EMA_SCALPING_STOP_LOSS_PCT,
            default="0.005",
        )

    def get_scalping_take_profit_pct(self) -> str:
        """Return the scalping take-profit ratio."""
        return self._get_var(
            ENV_SCALPING_TAKE_PROFIT_PCT,
            ENV_EMA_SCALPING_TAKE_PROFIT_PCT,
            default="0.01",
        )

    def get_trend_stop_loss_pct(self) -> str:
        """Return the trend stop-loss ratio."""
        return self._get_var(
            ENV_TREND_STOP_LOSS_PCT,
            ENV_EMA_CROSS_STOP_LOSS_PCT,
            default="0.015",
        )

    def get_trend_take_profit_pct(self) -> str:
        """Return the trend take-profit ratio."""
        return self._get_var(
            ENV_TREND_TAKE_PROFIT_PCT,
            ENV_EMA_CROSS_TAKE_PROFIT_PCT,
            default="0.03",
        )

    def get_swing_stop_loss_pct(self) -> str:
        """Return the swing stop-loss ratio."""
        return self._get_var(
            ENV_SWING_STOP_LOSS_PCT,
            default="0.025",
        )

    def get_swing_take_profit_pct(self) -> str:
        """Return the swing take-profit ratio."""
        return self._get_var(
            ENV_SWING_TAKE_PROFIT_PCT,
            default="0.05",
        )

    def get_stop_loss_pct(self) -> str:
        """Return the global/fallback stop-loss ratio."""
        return self._get_var(
            ENV_STOP_LOSS_PCT,
            default="0.02",
        )

    def get_take_profit_pct(self) -> str:
        """Return the global/fallback take-profit ratio."""
        return self._get_var(
            ENV_TAKE_PROFIT_PCT,
            default="0.04",
        )

    def get_ema_cross_stop_loss_pct(self) -> str:
        """Return the EMA cross stop-loss ratio."""
        return self._get_var(
            ENV_EMA_CROSS_STOP_LOSS_PCT,
            default="0.02",
        )

    def get_ema_cross_take_profit_pct(self) -> str:
        """Return the EMA cross take-profit ratio."""
        return self._get_var(
            ENV_EMA_CROSS_TAKE_PROFIT_PCT,
            default="0.04",
        )

    def get_ema_scalping_stop_loss_pct(self) -> str:
        """Return the EMA scalping stop-loss ratio (legacy alias)."""
        return self.get_scalping_stop_loss_pct()

    def get_ema_scalping_take_profit_pct(self) -> str:
        """Return the EMA scalping take-profit ratio (legacy alias)."""
        return self.get_scalping_take_profit_pct()

    def get_pier_stop_loss_pct(self) -> str:
        """Return the PIER price action stop-loss ratio."""
        return self._get_var(ENV_PIER_STOP_LOSS_PCT, default="0.012")

    def get_pier_take_profit_pct(self) -> str:
        """Return the PIER price action take-profit ratio."""
        return self._get_var(ENV_PIER_TAKE_PROFIT_PCT, default="0.024")

    def get_pier_trend_period(self) -> str:
        """Return the PIER macro trend EMA period."""
        return self._get_var(ENV_PIER_TREND_PERIOD, default="")

    def get_pier_pullback_period(self) -> str:
        """Return the PIER dynamic pullback EMA period."""
        return self._get_var(ENV_PIER_PULLBACK_PERIOD, default="")

    def get_pier_rsi_period(self) -> str:
        """Return the PIER RSI period."""
        return self._get_var(ENV_PIER_RSI_PERIOD, default="")

    def get_pier_rsi_long_min(self) -> str:
        """Return the lower bound of PIER long RSI pullback zone."""
        return self._get_var(ENV_PIER_RSI_LONG_MIN, default="38.0")

    def get_pier_rsi_long_max(self) -> str:
        """Return the upper bound of PIER long RSI pullback zone."""
        return self._get_var(ENV_PIER_RSI_LONG_MAX, default="58.0")

    def get_pier_rsi_short_min(self) -> str:
        """Return the lower bound of PIER short RSI pullback zone."""
        return self._get_var(ENV_PIER_RSI_SHORT_MIN, default="42.0")

    def get_pier_rsi_short_max(self) -> str:
        """Return the upper bound of PIER short RSI pullback zone."""
        return self._get_var(ENV_PIER_RSI_SHORT_MAX, default="62.0")

    def get_pier_volume_period(self) -> str:
        """Return the PIER volume SMA period."""
        return self._get_var(ENV_PIER_VOLUME_PERIOD, default="")

    def get_pier_volume_multiplier(self) -> str:
        """Return the PIER volume confirmation threshold multiplier."""
        return self._get_var(ENV_PIER_VOLUME_MULTIPLIER, default="")

    def get_pier_min_wick_ratio(self) -> str:
        """Return the PIER minimum pinbar rejection wick ratio."""
        return self._get_var(ENV_PIER_MIN_WICK_RATIO, default="")

    def get_pier_max_opposite_wick_ratio(self) -> str:
        """Return the PIER maximum opposite wick ratio."""
        return self._get_var(ENV_PIER_MAX_OPPOSITE_WICK_RATIO, default="")

    def get_pier_min_engulfing_body_ratio(self) -> str:
        """Return the PIER minimum engulfing body ratio."""
        return self._get_var(ENV_PIER_MIN_ENGULFING_BODY_RATIO, default="")

    def get_pier_atr_period(self) -> str:
        """Return the PIER ATR calculation period."""
        return self._get_var(ENV_PIER_ATR_PERIOD, default="")

    def get_pier_atr_sl_multiplier(self) -> str:
        """Return the PIER ATR multiplier for structural stop-loss."""
        return self._get_var(ENV_PIER_ATR_SL_MULTIPLIER, default="")

    def get_pier_risk_reward_ratio(self) -> str:
        """Return the configured Risk-Reward Ratio for PIER strategy."""
        return self._get_var(ENV_PIER_RISK_REWARD_RATIO, default="")

    def get_pier_min_confidence(self) -> str:
        """Return the PIER minimum acceptance confidence threshold."""
        return self._get_var(ENV_PIER_MIN_CONFIDENCE, default="")

    def get_pier_use_open_interest(self) -> bool:
        """Return whether PIER uses open interest confluence filter."""
        return self._get_bool(ENV_PIER_USE_OPEN_INTEREST, default=True)

    def get_pier_min_oi_change_pct(self) -> str:
        """Return the PIER minimum open interest change percentage."""
        return self._get_var(ENV_PIER_MIN_OI_CHANGE_PCT, default="")

    def get_pier_oi_confidence_bonus(self) -> str:
        """Return the PIER open interest confidence bonus."""
        return self._get_var(ENV_PIER_OI_CONFIDENCE_BONUS, default="")

    def get_pier_require_oi_confluence(self) -> bool:
        """Return whether PIER strictly requires open interest confluence."""
        return self._get_bool(ENV_PIER_REQUIRE_OI_CONFLUENCE, default=False)

    def get_pier_require_key_level_location(self) -> bool:
        """Return whether PIER requires key level location confirmation."""
        return self._get_bool(ENV_PIER_REQUIRE_KEY_LEVEL_LOCATION, default=True)

    def get_pier_swing_lookback(self) -> str:
        """Return the PIER swing high/low lookback period."""
        return self._get_var(ENV_PIER_SWING_LOOKBACK, default="")

    def get_pier_require_trend_filter(self) -> bool:
        """Return whether PIER requires dual EMA trend alignment."""
        return self._get_bool(ENV_PIER_REQUIRE_TREND_FILTER, default=True)

    def get_pier_min_natr_threshold(self) -> str:
        """Return the PIER minimum NATR threshold for dead market filtering."""
        return self._get_var(ENV_PIER_MIN_NATR_THRESHOLD, default="")

    def get_pier_min_sl_distance_pct(self) -> str:
        """Return the PIER minimum stop loss distance ratio."""
        return self._get_var(ENV_PIER_MIN_SL_DISTANCE_PCT, default="")

    def get_pier_location_tolerance_pct(self) -> str:
        """Return the PIER location tolerance percentage."""
        return self._get_var(ENV_PIER_LOCATION_TOLERANCE_PCT, default="")

    def get_pier_location_atr_multiplier(self) -> str:
        """Return the optional PIER location ATR multiplier."""
        return self._get_var(ENV_PIER_LOCATION_ATR_MULTIPLIER, default="")

    def get_pier_pullback_proximity_pct(self) -> str:
        """Return the PIER pullback proximity percentage."""
        return self._get_var(ENV_PIER_PULLBACK_PROXIMITY_PCT, default="")

    def get_pier_pullback_atr_multiplier(self) -> str:
        """Return the optional PIER pullback ATR multiplier."""
        return self._get_var(ENV_PIER_PULLBACK_ATR_MULTIPLIER, default="")

    def get_pier_pinbar_min_range_atr(self) -> str:
        """Return the optional PIER pinbar minimum range in ATR."""
        return self._get_var(ENV_PIER_PINBAR_MIN_RANGE_ATR, default="")

    def get_pier_engulfing_min_body_atr(self) -> str:
        """Return the optional PIER engulfing minimum body in ATR."""
        return self._get_var(ENV_PIER_ENGULFING_MIN_BODY_ATR, default="")

    def get_pier_require_confirmation(self) -> bool:
        """Return whether PIER requires breakout candle confirmation."""
        return self._get_bool(ENV_PIER_REQUIRE_CONFIRMATION, default=False)

    def get_pier_filter_account_ratio(self) -> bool:
        """Return whether PIER filters by account long-short ratio."""
        return self._get_bool(ENV_PIER_FILTER_ACCOUNT_RATIO, default=True)

    def get_pier_max_long_account_ratio(self) -> str:
        """Return the PIER maximum long account ratio."""
        return self._get_var(ENV_PIER_MAX_LONG_ACCOUNT_RATIO, default="")

    def get_pier_min_short_account_ratio(self) -> str:
        """Return the PIER minimum short account ratio."""
        return self._get_var(ENV_PIER_MIN_SHORT_ACCOUNT_RATIO, default="")

    def get_pier_require_account_ratio_confluence(self) -> bool:
        """Return whether PIER strictly requires account ratio confluence."""
        return self._get_bool(
            ENV_PIER_REQUIRE_ACCOUNT_RATIO_CONFLUENCE,
            default=False,
        )

    def get_pier_confirm_htf_account_ratio(self) -> bool:
        """Return whether PIER confirms with HTF account ratio."""
        return self._get_bool(ENV_PIER_CONFIRM_HTF_ACCOUNT_RATIO, default=False)

    def get_pier_include_star_patterns(self) -> bool:
        """Return whether PIER detects Morning/Evening Star patterns."""
        return self._get_bool(ENV_PIER_INCLUDE_STAR_PATTERNS, default=True)

    def get_pier_use_parabolic_sar(self) -> bool:
        """Return whether PIER uses Parabolic SAR directional filter."""
        return self._get_bool(ENV_PIER_USE_PARABOLIC_SAR, default=True)

    def get_pier_use_macd(self) -> bool:
        """Return whether PIER uses MACD momentum direction guard."""
        return self._get_bool(ENV_PIER_USE_MACD, default=True)

    def get_pier_macd_fast_period(self) -> str:
        """Return the PIER MACD fast period."""
        return self._get_var(ENV_PIER_MACD_FAST_PERIOD, default="")

    def get_pier_macd_slow_period(self) -> str:
        """Return the PIER MACD slow period."""
        return self._get_var(ENV_PIER_MACD_SLOW_PERIOD, default="")

    def get_pier_macd_signal_period(self) -> str:
        """Return the PIER MACD signal period."""
        return self._get_var(ENV_PIER_MACD_SIGNAL_PERIOD, default="")

    def get_pier_use_stoch_rsi(self) -> bool:
        """Return whether PIER uses Stochastic RSI timing guard."""
        return self._get_bool(ENV_PIER_USE_STOCH_RSI, default=True)

    def get_pier_stoch_rsi_period(self) -> str:
        """Return the PIER Stochastic RSI period."""
        return self._get_var(ENV_PIER_STOCH_RSI_PERIOD, default="")

    def get_pier_stoch_rsi_k_period(self) -> str:
        """Return the PIER Stochastic RSI %K smoothing period."""
        return self._get_var(ENV_PIER_STOCH_RSI_K_PERIOD, default="")

    def get_pier_stoch_rsi_d_period(self) -> str:
        """Return the PIER Stochastic RSI %D smoothing period."""
        return self._get_var(ENV_PIER_STOCH_RSI_D_PERIOD, default="")

    def get_pier_stoch_rsi_overbought(self) -> str:
        """Return the PIER Stochastic RSI overbought threshold."""
        return self._get_var(ENV_PIER_STOCH_RSI_OVERBOUGHT, default="")

    def get_pier_stoch_rsi_oversold(self) -> str:
        """Return the PIER Stochastic RSI oversold threshold."""
        return self._get_var(ENV_PIER_STOCH_RSI_OVERSOLD, default="")

    def get_pier_use_structural_tp(self) -> bool:
        """Return whether PIER uses dynamic structural target trimming."""
        return self._get_bool(ENV_PIER_USE_STRUCTURAL_TP, default=True)

    def get_pier_structural_tp_buffer_pct(self) -> str:
        """Return the buffer fraction subtracted from structural barrier."""
        return self._get_var(ENV_PIER_STRUCTURAL_TP_BUFFER_PCT, default="0.002")

    def get_pier_min_structural_rr(self) -> str:
        """Return the minimum acceptable reward-to-risk ratio after trimming."""
        return self._get_var(ENV_PIER_MIN_STRUCTURAL_RR, default="1.0")

    def get_pier_bb_period(self) -> str:
        """Return the Bollinger Bands period for structural target calculation."""
        return self._get_var(ENV_PIER_BB_PERIOD, default="")

    def get_pier_bb_std_dev(self) -> str:
        """Return the Bollinger Bands std dev for structural target calculation."""
        return self._get_var(ENV_PIER_BB_STD_DEV, default="")

    def get_pier_use_htf_structural_tp(self) -> bool:
        """Return whether PIER uses HTF 1h structural target trimming."""
        return self._get_bool(ENV_PIER_USE_HTF_STRUCTURAL_TP, default=True)

    def get_pier_htf_bb_period(self) -> str:
        """Return the HTF Bollinger Bands period for structural target calculation."""
        return self._get_var(ENV_PIER_HTF_BB_PERIOD, default="")

    def get_pier_htf_bb_std_dev(self) -> str:
        """Return the HTF Bollinger Bands std dev for structural target calculation."""
        return self._get_var(ENV_PIER_HTF_BB_STD_DEV, default="")

    def get_pier_htf_interval(self) -> str:
        """Return the configured PIER HTF interval or empty string."""
        return self._get_var(ENV_PIER_HTF_INTERVAL, default="")

    def get_pier_leverage(self) -> str:
        """Return the PIER-specific leverage override or empty string."""
        return self._get_var(ENV_PIER_LEVERAGE, default="")

    def get_pier_max_position_size_usdt(self) -> str:
        """Return the PIER-specific max position size in USDT or empty string."""
        return self._get_var(ENV_PIER_MAX_POSITION_SIZE_USDT, default="")

    def get_pier_risk_per_trade_pct(self) -> str:
        """Return the PIER-specific risk per trade percentage or empty string."""
        return self._get_var(ENV_PIER_RISK_PER_TRADE_PCT, default="")

    def get_pier_trailing_mode(self) -> str:
        """Return the PIER-specific trailing mode override or empty string."""
        return self._get_var(ENV_PIER_TRAILING_MODE, default="")

    def get_pier_trailing_swing_timeframe(self) -> str:
        """Return the PIER-specific trailing swing timeframe or empty string."""
        return self._get_var(ENV_PIER_TRAILING_SWING_TIMEFRAME, default="")

    def get_pier_trailing_swing_window(self) -> str:
        """Return the PIER-specific trailing swing window or empty string."""
        return self._get_var(ENV_PIER_TRAILING_SWING_WINDOW, default="")

    def get_pier_trailing_buffer_pct(self) -> str:
        """Return the PIER-specific trailing buffer percentage or empty string."""
        return self._get_var(ENV_PIER_TRAILING_BUFFER_PCT, default="")

    def get_pier_partial_tp_enabled(self) -> bool | None:
        """Return the PIER-specific partial TP enabled override or None if unset."""
        raw = self._get_var(ENV_PIER_PARTIAL_TP_ENABLED, default="")
        if not raw:
            return None
        return raw.lower().strip() in ("true", "1", "yes", "on")

    def get_pier_partial_tp_ratio(self) -> str:
        """Return the PIER-specific partial TP ratio or empty string."""
        return self._get_var(ENV_PIER_PARTIAL_TP_RATIO, default="")

    def get_pier_partial_tp_trigger_progress(self) -> str:
        """Return the PIER-specific partial TP trigger progress or empty string."""
        return self._get_var(ENV_PIER_PARTIAL_TP_TRIGGER_PROGRESS, default="")

    def get_pier_enable_early_position_exit(self) -> bool | None:
        """Return PIER-specific early position exit override or None if unset."""
        raw = self._get_var(ENV_PIER_ENABLE_EARLY_POSITION_EXIT, default="")
        if not raw:
            return None
        return raw.lower().strip() in ("true", "1", "yes", "on")

    def get_pier_early_exit_min_confidence(self) -> str:
        """Return the PIER-specific early exit min confidence or empty string."""
        return self._get_var(ENV_PIER_EARLY_EXIT_MIN_CONFIDENCE, default="")

    def get_pier_early_exit_check_candlestick_reversal(self) -> bool | None:
        """Return PIER early exit candlestick reversal check override or None."""
        raw = self._get_var(ENV_PIER_EARLY_EXIT_CHECK_CANDLESTICK_REVERSAL, default="")
        if not raw:
            return None
        return raw.lower().strip() in ("true", "1", "yes", "on")

    def get_pier_early_exit_check_opposite_signal(self) -> bool | None:
        """Return PIER early exit opposite signal check override or None."""
        raw = self._get_var(ENV_PIER_EARLY_EXIT_CHECK_OPPOSITE_SIGNAL, default="")
        if not raw:
            return None
        return raw.lower().strip() in ("true", "1", "yes", "on")

    def get_pier_early_exit_check_exhaustion(self) -> bool | None:
        """Return PIER early exit exhaustion check override or None."""
        raw = self._get_var(ENV_PIER_EARLY_EXIT_CHECK_EXHAUSTION, default="")
        if not raw:
            return None
        return raw.lower().strip() in ("true", "1", "yes", "on")

    def get_ny_range_risk_reward_ratio(self) -> str:
        """Return the configured Risk-Reward Ratio for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_RISK_REWARD_RATIO, default="")

    def get_ny_range_max_sl_pct(self) -> str:
        """Return the configured maximum SL percentage for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_MAX_SL_PCT, default="")

    def get_ny_range_min_sl_pct(self) -> str:
        """Return the configured minimum SL percentage for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_MIN_SL_PCT, default="")

    def get_ny_range_fallback_sl_pct(self) -> str:
        """Return the configured fallback SL percentage for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_FALLBACK_SL_PCT, default="")

    def get_ny_range_max_breakout_bars(self) -> str:
        """Return the maximum breakout candles count for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_MAX_BREAKOUT_BARS, default="")

    def get_ny_range_min_confidence(self) -> str:
        """Return the minimum confidence threshold for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_MIN_CONFIDENCE, default="")

    def get_ny_range_base_confidence(self) -> str:
        """Return the base confidence score for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_BASE_CONFIDENCE, default="")

    def get_ny_range_use_volume_filter(self) -> bool:
        """Return whether NY 4H range scalping uses volume confirmation."""
        return self._get_bool(ENV_NY_RANGE_USE_VOLUME_FILTER, default=True)

    def get_ny_range_volume_period(self) -> str:
        """Return volume SMA period for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_VOLUME_PERIOD, default="")

    def get_ny_range_volume_multiplier(self) -> str:
        """Return volume threshold multiplier for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_VOLUME_MULTIPLIER, default="")

    def get_ny_range_volume_confidence_bonus(self) -> str:
        """Return volume confidence bonus for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_VOLUME_CONFIDENCE_BONUS, default="")

    def get_ny_range_require_volume_confirmation(self) -> bool:
        """Return whether NY 4H range scalping strictly requires volume."""
        return self._get_bool(ENV_NY_RANGE_REQUIRE_VOLUME_CONFIRMATION, default=False)

    def get_ny_range_require_trend_filter(self) -> bool:
        """Return whether NY 4H range scalping requires EMA trend filter."""
        return self._get_bool(ENV_NY_RANGE_REQUIRE_TREND_FILTER, default=True)

    def get_ny_range_trend_ema_period(self) -> str:
        """Return trend EMA period for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_TREND_EMA_PERIOD, default="")

    def get_ny_range_use_rsi_filter(self) -> bool:
        """Return whether NY 4H range scalping uses RSI momentum filter."""
        return self._get_bool(ENV_NY_RANGE_USE_RSI_FILTER, default=True)

    def get_ny_range_rsi_period(self) -> str:
        """Return RSI period for NY 4H range scalping."""
        return self._get_var(ENV_NY_RANGE_RSI_PERIOD, default="")

    def get_ny_range_rsi_long_max(self) -> str:
        """Return maximum RSI allowed for long re-entries."""
        return self._get_var(ENV_NY_RANGE_RSI_LONG_MAX, default="")

    def get_ny_range_rsi_short_min(self) -> str:
        """Return minimum RSI allowed for short re-entries."""
        return self._get_var(ENV_NY_RANGE_RSI_SHORT_MIN, default="")

    def get_origin_risk_reward_ratio(self) -> str:
        """Return the configured Risk-Reward Ratio for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_RISK_REWARD_RATIO, default="")

    def get_origin_stop_loss_pct(self) -> str:
        """Return safety boundary / fallback Stop Loss pct for Botragram Origin."""
        return self._get_var(ENV_ORIGIN_STOP_LOSS_PCT, default="")

    def get_origin_take_profit_pct(self) -> str:
        """Return safety boundary / fallback Take Profit pct for Botragram Origin."""
        return self._get_var(ENV_ORIGIN_TAKE_PROFIT_PCT, default="")

    def get_origin_min_sl_pct(self) -> str:
        """Return the configured minimum SL percentage for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_MIN_SL_PCT, default="")

    def get_origin_max_sl_pct(self) -> str:
        """Return the configured maximum SL percentage for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_MAX_SL_PCT, default="")

    def get_origin_fallback_sl_pct(self) -> str:
        """Return the fallback SL percentage for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_FALLBACK_SL_PCT, default="")

    def get_origin_min_confidence(self) -> str:
        """Return the minimum confidence threshold for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_MIN_CONFIDENCE, default="")

    def get_origin_use_trend_filter(self) -> bool:
        """Return whether Botragram Origin strategy uses trend filter."""
        return self._get_bool(ENV_ORIGIN_USE_TREND_FILTER, default=False)

    def get_origin_trend_ema_period(self) -> str:
        """Return trend EMA period for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_TREND_EMA_PERIOD, default="")

    def get_origin_use_volume_filter(self) -> bool:
        """Return whether Botragram Origin strategy uses volume filter."""
        return self._get_bool(ENV_ORIGIN_USE_VOLUME_FILTER, default=False)

    def get_origin_volume_period(self) -> str:
        """Return volume SMA period for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_VOLUME_PERIOD, default="")

    def get_origin_volume_multiplier(self) -> str:
        """Return volume multiplier for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_VOLUME_MULTIPLIER, default="")

    def get_origin_use_rsi_filter(self) -> bool:
        """Return whether Botragram Origin strategy uses RSI filter."""
        return self._get_bool(ENV_ORIGIN_USE_RSI_FILTER, default=False)

    def get_origin_rsi_period(self) -> str:
        """Return RSI period for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_RSI_PERIOD, default="")

    def get_origin_rsi_long_max(self) -> str:
        """Return maximum RSI allowed for long entry in Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_RSI_LONG_MAX, default="")

    def get_origin_rsi_short_min(self) -> str:
        """Return minimum RSI allowed for short entry in Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_RSI_SHORT_MIN, default="")

    def get_origin_require_rsi_direction(self) -> bool:
        """Return whether Botragram Origin strategy requires RSI momentum direction."""
        return self._get_bool(ENV_ORIGIN_REQUIRE_RSI_DIRECTION, default=False)

    def get_origin_use_bb_filter(self) -> bool:
        """Return whether Botragram Origin strategy uses Bollinger Bands filter."""
        return self._get_bool(ENV_ORIGIN_USE_BB_FILTER, default=False)

    def get_origin_bb_period(self) -> str:
        """Return Bollinger Bands period for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_BB_PERIOD, default="")

    def get_origin_bb_std_dev(self) -> str:
        """Return Bollinger Bands standard deviation for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_BB_STD_DEV, default="")

    def get_origin_use_macd_filter(self) -> bool:
        """Return whether Botragram Origin strategy uses MACD filter."""
        return self._get_bool(ENV_ORIGIN_USE_MACD_FILTER, default=False)

    def get_origin_macd_fast_period(self) -> str:
        """Return MACD fast period for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_MACD_FAST_PERIOD, default="")

    def get_origin_macd_slow_period(self) -> str:
        """Return MACD slow period for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_MACD_SLOW_PERIOD, default="")

    def get_origin_macd_signal_period(self) -> str:
        """Return MACD signal period for Botragram Origin strategy."""
        return self._get_var(ENV_ORIGIN_MACD_SIGNAL_PERIOD, default="")

    def get_origin_use_psar_filter(self) -> bool:
        """Return whether Botragram Origin strategy uses Parabolic SAR filter."""
        return self._get_bool(ENV_ORIGIN_USE_PSAR_FILTER, default=False)

    def get_origin_psar_max_proximity_pct(self) -> str:
        """Return the maximum allowed PSAR proximity distance for Botragram Origin."""
        return self._get_var(ENV_ORIGIN_PSAR_MAX_PROXIMITY_PCT, default="")

    def get_max_open_positions(self) -> str:
        """Return the configured limit for concurrently open positions."""
        return self._get_var(ENV_MAX_OPEN_POSITIONS, default="1")

    def get_max_position_size_usdt(self) -> str:
        """Return the configured maximum position notional in USDT."""
        return self._get_var(ENV_MAX_POSITION_SIZE_USDT, default="1000")

    def get_risk_per_trade_pct(self) -> str:
        """Return the configured maximum account risk for one trade."""
        return self._get_var(ENV_RISK_PER_TRADE_PCT, default="0.02")

    def get_max_drawdown_pct(self) -> str:
        """Return the configured maximum account drawdown ratio."""
        return self._get_var(ENV_MAX_DRAWDOWN_PCT, default="0.10")

    def get_leverage(self) -> str:
        """Return the configured risk-sizing leverage."""
        return self._get_var(ENV_LEVERAGE, default="1")

    def get_max_executable_quote_age_ms(self) -> str:
        """Return the maximum acceptable MARKET quote age in milliseconds."""
        return self._get_var(ENV_MAX_EXECUTABLE_QUOTE_AGE_MS, default="1000")

    def get_max_spread_bps(self) -> str:
        """Return the maximum acceptable MARKET bid/ask spread in basis points."""
        return self._get_var(ENV_MAX_SPREAD_BPS, default="20")

    def get_global_market_interval(self) -> str:
        """Return the configured global market candle interval with legacy fallback."""
        canonical = self._get_var(ENV_GLOBAL_MARKET_INTERVAL)
        if canonical:
            return canonical
        return self._get_var(ENV_MARKET_INTERVAL)

    def has_legacy_market_interval_only(self) -> bool:
        """Return True if legacy MARKET_INTERVAL is set without canonical key."""
        legacy = self._get_var(ENV_MARKET_INTERVAL)
        canonical = self._get_var(ENV_GLOBAL_MARKET_INTERVAL)
        return bool(legacy) and not bool(canonical)

    def get_market_interval(self) -> str:
        """Return the optional configured candle interval.

        This method is preserved for backward compatibility and delegates
        to get_global_market_interval.
        """
        return self.get_global_market_interval()

    def get_market_symbol(self) -> str:
        """Return the optional configured trading symbol (e.g. XAUUSD, BTCUSDT)."""
        symbol = self._get_var(ENV_SYMBOL)
        if symbol:
            return symbol
        return self._get_var(ENV_MARKET_SYMBOL)

    def get_base_asset(self) -> str:
        """Return the optional configured base asset (e.g. XAU, EUR, BTC)."""
        return self._get_var(ENV_BASE_ASSET)

    def get_quote_asset(self) -> str:
        """Return the optional configured quote asset (e.g. USD, USDT)."""
        return self._get_var(ENV_QUOTE_ASSET)

    def get_cfd_symbol(self) -> str:
        """Return the optional configured CFD market symbol (e.g. XAUUSD)."""
        return self._get_var(ENV_CFD_SYMBOL)

    def get_futures_symbol(self) -> str:
        """Return the optional configured Futures market symbol (e.g. BTCUSDT)."""
        return self._get_var(ENV_FUTURES_SYMBOL)

    def get_spot_symbol(self) -> str:
        """Return the optional configured Spot market symbol (e.g. BTCUSDT)."""
        return self._get_var(ENV_SPOT_SYMBOL)

    def get_cfd_quote_asset(self) -> str:
        """Return the optional configured CFD quote asset (e.g. USD)."""
        return self._get_var(ENV_CFD_QUOTE_ASSET)

    def get_futures_quote_asset(self) -> str:
        """Return the optional configured Futures quote asset (e.g. USDT)."""
        return self._get_var(ENV_FUTURES_QUOTE_ASSET)

    def get_strategy_timeframe_override_enabled(self) -> bool:
        """Return whether active strategy timeframe override is enabled."""
        return self._get_bool(
            ENV_STRATEGY_TIMEFRAME_OVERRIDE_ENABLED,
            default=False,
        )

    def get_strategy_timeframe_override(self) -> str:
        """Return the optional active strategy timeframe override string."""
        return self._get_var(ENV_STRATEGY_TIMEFRAME_OVERRIDE)

    def get_strategy_interval(
        self, strategy_type: StrategyType | str
    ) -> tuple[str, str]:
        """Return (raw_value, source_name) for a specific strategy's timeframe.

        Checks strategy-specific environment variables, user-friendly aliases
        (_INTERVAL, _TIMEFRAME, _TF), and category fallbacks (e.g. SCALPING_INTERVAL).
        """
        st_val = (
            strategy_type.value
            if isinstance(strategy_type, StrategyType)
            else strategy_type.lower().strip()
        )
        candidates: list[str] = []
        if st_val == "pinbar_engulfing_ema_rsi":
            candidates = [
                "PIER_INTERVAL",
                "PIER_TIMEFRAME",
                "PIER_TF",
                "PINBAR_ENGULFING_EMA_RSI_INTERVAL",
            ]
        elif st_val == "botragram_origin":
            candidates = [
                "ORIGIN_INTERVAL",
                "ORIGIN_TIMEFRAME",
                "ORIGIN_TF",
                "BOTRAGRAM_INTERVAL",
                "BOTRAGRAM_TIMEFRAME",
                "BOTRAGRAM_TF",
            ]
        elif st_val == "morph":
            candidates = ["MORPH_INTERVAL", "MORPH_TIMEFRAME", "MORPH_TF"]
        elif st_val == "choch_fvg":
            candidates = [
                "CHOCH_INTERVAL",
                "CHOCH_FVG_INTERVAL",
                "CHOCH_TIMEFRAME",
                "CHOCH_TF",
            ]
        elif st_val == "choch_rsi_bb_hybrid":
            candidates = [
                "CRBB_INTERVAL",
                "CRBB_TIMEFRAME",
                "CRBB_TF",
                "CHOCH_RSI_BB_HYBRID_INTERVAL",
            ]
        elif st_val == "high_confluence_exhaustion":
            candidates = [
                "HCE_INTERVAL",
                "HCE_TIMEFRAME",
                "HCE_TF",
                "HIGH_CONFLUENCE_EXHAUSTION_INTERVAL",
            ]
        elif st_val == "liquidity_sweep_exhaustion":
            candidates = [
                "LSE_INTERVAL",
                "LSE_TIMEFRAME",
                "LSE_TF",
                "LIQUIDITY_SWEEP_EXHAUSTION_INTERVAL",
            ]
        elif st_val == "ny_4h_range_scalping":
            candidates = [
                "NY_RANGE_INTERVAL",
                "NY_RANGE_TIMEFRAME",
                "NY_RANGE_TF",
                "NY_4H_RANGE_SCALPING_INTERVAL",
            ]
        elif st_val == "quad_confluence":
            candidates = [
                "QUAD_INTERVAL",
                "QUAD_CONFLUENCE_INTERVAL",
                "QUAD_TIMEFRAME",
                "QUAD_TF",
                "TREND_INTERVAL",
                "TREND_TIMEFRAME",
                "TREND_TF",
            ]
        elif st_val in ("ema_scalping", "rsi_bb_scalping", "vwap_breakout"):
            prefix = st_val.upper()
            candidates = [
                f"{prefix}_INTERVAL",
                f"{prefix}_TIMEFRAME",
                f"{prefix}_TF",
                "SCALPING_INTERVAL",
                "SCALPING_TIMEFRAME",
                "SCALPING_TF",
            ]
        elif st_val == "macd_swing":
            candidates = [
                "MACD_SWING_INTERVAL",
                "MACD_SWING_TIMEFRAME",
                "MACD_SWING_TF",
                "SWING_INTERVAL",
                "SWING_TIMEFRAME",
                "SWING_TF",
            ]
        elif st_val in (
            "ema_cross",
            "ema_rsi",
            "supertrend",
            "ichimoku_cloud",
            "adx_trend",
            "bollinger_breakout",
        ):
            prefix = st_val.upper()
            candidates = [
                f"{prefix}_INTERVAL",
                f"{prefix}_TIMEFRAME",
                f"{prefix}_TF",
                "TREND_INTERVAL",
                "TREND_TIMEFRAME",
                "TREND_TF",
            ]
        else:
            prefix = st_val.upper()
            candidates = [
                f"{prefix}_INTERVAL",
                f"{prefix}_TIMEFRAME",
                f"{prefix}_TF",
            ]

        for key in candidates:
            val = self._get_var(key)
            if val:
                return val, key
        return "", ""

    def get_discovery_max_universe_symbols(self) -> str:
        """Return the optional ceiling on the rotated ranked discovery universe."""
        return self._get_var(ENV_DISCOVERY_MAX_UNIVERSE_SYMBOLS)

    def get_discovery_universe_limit(self) -> str:
        """Return the maximum ranked symbols retained in one sweep."""
        return self._get_var(ENV_DISCOVERY_UNIVERSE_LIMIT, default="100")

    def get_discovery_batch_size(self) -> str:
        """Return the number of ranked symbols evaluated per global cycle."""
        return self._get_var(ENV_DISCOVERY_BATCH_SIZE, default="20")

    def get_discovery_cadence_seconds(self) -> str:
        """Return the optional autonomous global discovery cadence."""
        return self._get_var(ENV_DISCOVERY_CADENCE_SECONDS)

    def get_discovery_candle_delay_seconds(self) -> str:
        """Return the optional pacing delay between candle requests in seconds."""
        return self._get_var(ENV_DISCOVERY_CANDLE_DELAY_SECONDS)

    def get_candle_retention_days(self) -> str:
        """Return the maximum age of stored candles before automated pruning."""
        return self._get_var(ENV_CANDLE_RETENTION_DAYS, default="7")

    def get_candle_pruning_interval_hours(self) -> str:
        """Return the background interval between automated candle pruning runs."""
        return self._get_var(ENV_CANDLE_PRUNING_INTERVAL_HOURS, default="6")

    def get_active_exchange(self) -> str:
        """Return the configured active exchange."""
        return self._get_var(
            ENV_ACTIVE_EXCHANGE,
            default="BINANCE",
        ).upper()

    # -------------------------------------------------------------------------
    # Binance
    # -------------------------------------------------------------------------

    def get_binance_api_key(self) -> str:
        """Return the Binance API key."""
        return self._get_var(
            ENV_BINANCE_API_KEY,
            ENV_EXCHANGE_API_KEY_LEGACY,
        )

    def get_binance_api_secret(self) -> str:
        """Return the Binance API secret."""
        return self._get_var(
            ENV_BINANCE_API_SECRET,
            ENV_EXCHANGE_API_SECRET_LEGACY,
        )

    def get_binance_market_type(self) -> str:
        """Return the selected Binance product family."""
        return self._get_var(
            ENV_BINANCE_MARKET_TYPE,
            default="SPOT",
        ).upper()

    def get_binance_testnet(self) -> bool:
        """Return whether Binance testnet mode is enabled."""
        return self._get_bool(
            ENV_BINANCE_TESTNET,
            default=True,
        )

    # -------------------------------------------------------------------------
    # Bitget
    # -------------------------------------------------------------------------

    def get_bitget_api_key(self) -> str:
        """Return the Bitget API key."""
        return self._get_var(
            ENV_BITGET_API_KEY,
            ENV_EXCHANGE_API_KEY_LEGACY,
        ).strip()

    def get_bitget_api_secret(self) -> str:
        """Return the Bitget API secret."""
        return self._get_var(
            ENV_BITGET_API_SECRET,
            ENV_EXCHANGE_API_SECRET_LEGACY,
        ).strip()

    def get_bitget_passphrase(self) -> str:
        """Return the Bitget API passphrase."""
        return self._get_var(ENV_BITGET_PASSPHRASE).strip()

    def get_bitget_market_type(self) -> str:
        """Return the selected Bitget product family."""
        return self._get_var(
            ENV_BITGET_MARKET_TYPE,
            default="FUTURES",
        ).upper()

    def get_bitget_testnet(self) -> bool:
        """Return whether Bitget testnet mode is enabled."""
        return self._get_bool(
            ENV_BITGET_TESTNET,
            default=True,
        )

    def get_bitget_margin_mode(self) -> str:
        """Return the Bitget margin mode (ISOLATED or CROSSED)."""
        return self._get_var(
            ENV_BITGET_MARGIN_MODE,
            ENV_MARGIN_MODE,
            default="ISOLATED",
        ).upper()

    def get_bitget_cfd_mode(self) -> str:
        """Return the Bitget CFD account mode (ecn, zero_fee, or pro)."""
        return (
            self._get_var(
                ENV_BITGET_CFD_MODE,
                default="ecn",
            )
            .strip()
            .lower()
        )

    def get_margin_mode(self) -> str:
        """Return the general margin mode (ISOLATED or CROSSED)."""
        return self._get_var(
            ENV_MARGIN_MODE,
            default="ISOLATED",
        ).upper()

    # -------------------------------------------------------------------------
    # Bybit
    # -------------------------------------------------------------------------

    def get_bybit_api_key(self) -> str:
        """Return the Bybit API key."""
        return self._get_var(
            ENV_BYBIT_API_KEY,
            ENV_EXCHANGE_API_KEY_LEGACY,
        )

    def get_bybit_api_secret(self) -> str:
        """Return the Bybit API secret."""
        return self._get_var(
            ENV_BYBIT_API_SECRET,
            ENV_EXCHANGE_API_SECRET_LEGACY,
        )

    def get_bybit_market_type(self) -> str:
        """Return the selected Bybit product family."""
        return self._get_var(
            ENV_BYBIT_MARKET_TYPE,
            default="FUTURES",
        ).upper()

    def get_bybit_testnet(self) -> bool:
        """Return whether Bybit testnet mode is enabled."""
        return self._get_bool(
            ENV_BYBIT_TESTNET,
            default=True,
        )

    def get_bybit_demo(self) -> bool:
        """Return whether Bybit Demo Trading mode is enabled."""
        return self._get_bool(
            ENV_BYBIT_DEMO,
            default=False,
        )

    # -------------------------------------------------------------------------
    # OKX
    # -------------------------------------------------------------------------

    def get_okx_api_key(self) -> str:
        """Return the OKX API key."""
        return self._get_var(
            ENV_OKX_API_KEY,
            ENV_EXCHANGE_API_KEY_LEGACY,
        )

    def get_okx_api_secret(self) -> str:
        """Return the OKX API secret."""
        return self._get_var(
            ENV_OKX_API_SECRET,
            ENV_EXCHANGE_API_SECRET_LEGACY,
        )

    def get_okx_passphrase(self) -> str:
        """Return the OKX API passphrase."""
        return self._get_var(ENV_OKX_PASSPHRASE)

    def get_okx_testnet(self) -> bool:
        """Return whether OKX testnet mode is enabled."""
        return self._get_bool(
            ENV_OKX_TESTNET,
            default=True,
        )

    # -------------------------------------------------------------------------
    # Active Exchange Compatibility
    # -------------------------------------------------------------------------

    def get_api_key(self) -> str:
        """Return the API key for the active exchange."""
        exchange = self.get_active_exchange()

        match exchange:
            case "BINANCE":
                return self.get_binance_api_key()
            case "BITGET":
                return self.get_bitget_api_key()
            case "BYBIT":
                return self.get_bybit_api_key()
            case "OKX":
                return self.get_okx_api_key()
            case _:
                raise ValueError(f"Unsupported active exchange: {exchange!r}")

    def get_api_secret(self) -> str:
        """Return the API secret for the active exchange."""
        exchange = self.get_active_exchange()

        match exchange:
            case "BINANCE":
                return self.get_binance_api_secret()
            case "BITGET":
                return self.get_bitget_api_secret()
            case "BYBIT":
                return self.get_bybit_api_secret()
            case "OKX":
                return self.get_okx_api_secret()
            case _:
                raise ValueError(f"Unsupported active exchange: {exchange!r}")

    def get_testnet(self) -> bool:
        """Return the testnet flag for the active exchange."""
        exchange = self.get_active_exchange()

        match exchange:
            case "BINANCE":
                return self.get_binance_testnet()
            case "BITGET":
                return self.get_bitget_testnet()
            case "BYBIT":
                return self.get_bybit_testnet()
            case "OKX":
                return self.get_okx_testnet()
            case _:
                raise ValueError(f"Unsupported active exchange: {exchange!r}")
