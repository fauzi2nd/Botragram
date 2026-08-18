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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.env import (
    ENV_ACTIVE_EXCHANGE,
    ENV_AI_MODEL,
    ENV_AI_PROVIDER,
    ENV_AUTONOMOUS_EXECUTION_ENABLED,
    ENV_AUTONOMOUS_LIVE_ENTRY_ENABLED,
    ENV_BINANCE_API_KEY,
    ENV_BINANCE_API_SECRET,
    ENV_BINANCE_MARKET_TYPE,
    ENV_BINANCE_TESTNET,
    ENV_BITGET_API_KEY,
    ENV_BITGET_API_SECRET,
    ENV_BITGET_PASSPHRASE,
    ENV_BITGET_TESTNET,
    ENV_BOTRAGRAM_ENV_FILE,
    ENV_BOTRAGRAM_PROFILE,
    ENV_BYBIT_API_KEY,
    ENV_BYBIT_API_SECRET,
    ENV_BYBIT_TESTNET,
    ENV_EMA_SCALPING_STOP_LOSS_PCT,
    ENV_EMA_SCALPING_TAKE_PROFIT_PCT,
    ENV_EXCHANGE_API_KEY_LEGACY,
    ENV_EXCHANGE_API_SECRET_LEGACY,
    ENV_EXECUTION_POLICY,
    ENV_GEMINI_API_KEY,
    ENV_LOG_LEVEL,
    ENV_LOG_LEVEL_LEGACY,
    ENV_MAX_OPEN_POSITIONS,
    ENV_MAX_POSITION_SIZE_USDT,
    ENV_OKX_API_KEY,
    ENV_OKX_API_SECRET,
    ENV_OKX_PASSPHRASE,
    ENV_OKX_TESTNET,
    ENV_OPENAI_API_KEY,
    ENV_OPENROUTER_API_KEY,
    ENV_TELEGRAM_CHAT_ID,
    ENV_TELEGRAM_TOKEN,
    ENV_TELEGRAM_TOKEN_LEGACY,
    ENV_TRADE_MODE,
    ENV_TRADE_MODE_LEGACY,
)
from botragram.enums import EnvironmentProfile

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

            if normalized_primary:
                return normalized_primary

        if fallback_key is not None:
            fallback_value = os.getenv(fallback_key)

            if fallback_value is not None:
                normalized_fallback = fallback_value.strip()

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
        return base_path.with_name(f"{base_path.name}.{profile.value}")

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

    def get_autonomous_execution_enabled(self) -> bool:
        """Return whether autonomous opportunity execution is enabled."""
        return self._get_bool(ENV_AUTONOMOUS_EXECUTION_ENABLED, default=False)

    def get_autonomous_live_entry_enabled(self) -> bool:
        """Return explicit opt-in for future TESTNET autonomous LIVE entry."""
        return self._get_bool(ENV_AUTONOMOUS_LIVE_ENTRY_ENABLED, default=False)

    def get_execution_policy(self) -> str:
        """Return the optional explicit runtime execution policy."""
        return self._get_var(ENV_EXECUTION_POLICY)

    def get_ema_scalping_stop_loss_pct(self) -> str:
        """Return the EMA scalping stop-loss ratio."""
        return self._get_var(
            ENV_EMA_SCALPING_STOP_LOSS_PCT,
            default="0.005",
        )

    def get_ema_scalping_take_profit_pct(self) -> str:
        """Return the EMA scalping take-profit ratio."""
        return self._get_var(
            ENV_EMA_SCALPING_TAKE_PROFIT_PCT,
            default="0.01",
        )

    def get_max_open_positions(self) -> str:
        """Return the configured limit for concurrently open positions."""
        return self._get_var(ENV_MAX_OPEN_POSITIONS, default="1")

    def get_max_position_size_usdt(self) -> str:
        """Return the configured maximum position notional in USDT."""
        return self._get_var(ENV_MAX_POSITION_SIZE_USDT, default="1000")

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
        )

    def get_bitget_api_secret(self) -> str:
        """Return the Bitget API secret."""
        return self._get_var(
            ENV_BITGET_API_SECRET,
            ENV_EXCHANGE_API_SECRET_LEGACY,
        )

    def get_bitget_passphrase(self) -> str:
        """Return the Bitget API passphrase."""
        return self._get_var(ENV_BITGET_PASSPHRASE)

    def get_bitget_testnet(self) -> bool:
        """Return whether Bitget testnet mode is enabled."""
        return self._get_bool(
            ENV_BITGET_TESTNET,
            default=True,
        )

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

    def get_bybit_testnet(self) -> bool:
        """Return whether Bybit testnet mode is enabled."""
        return self._get_bool(
            ENV_BYBIT_TESTNET,
            default=True,
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
