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

# =============================================================================
# Third-Party Imports
# =============================================================================
from dotenv import load_dotenv

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.env import (
    ENV_ACTIVE_EXCHANGE,
    ENV_AI_MODEL,
    ENV_AI_PROVIDER,
    ENV_BINANCE_API_KEY,
    ENV_BINANCE_API_SECRET,
    ENV_BINANCE_TESTNET,
    ENV_BITGET_API_KEY,
    ENV_BITGET_API_SECRET,
    ENV_BITGET_PASSPHRASE,
    ENV_BITGET_TESTNET,
    ENV_BYBIT_API_KEY,
    ENV_BYBIT_API_SECRET,
    ENV_BYBIT_TESTNET,
    ENV_EXCHANGE_API_KEY_LEGACY,
    ENV_EXCHANGE_API_SECRET_LEGACY,
    ENV_GEMINI_API_KEY,
    ENV_LOG_LEVEL,
    ENV_LOG_LEVEL_LEGACY,
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


# =============================================================================
# Environment Provider
# =============================================================================
class EnvironmentProvider:
    """Provide normalized access to Botragram environment variables."""

    __slots__ = ("_env_path",)

    def __init__(
        self,
        env_path: str = ".env",
        *,
        override: bool = False,
    ) -> None:
        """Load environment variables from a dotenv file.

        Args:
            env_path: Path to the dotenv file.
            override: Whether dotenv values override existing environment
                variables.
        """
        normalized_path = env_path.strip()

        if not normalized_path:
            raise ValueError("Environment file path must not be empty")

        self._env_path = normalized_path

        load_dotenv(
            dotenv_path=self._env_path,
            override=override,
        )

    @property
    def env_path(self) -> str:
        """Return the configured dotenv file path."""
        return self._env_path

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

        normalized = raw_value.casefold()

        if normalized in _TRUE_VALUES:
            return True

        if normalized in _FALSE_VALUES:
            return False

        raise ValueError(
            f"Environment variable {key!r} must be one of "
            f"{sorted(_TRUE_VALUES | _FALSE_VALUES)!r}, "
            f"not {raw_value!r}"
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
