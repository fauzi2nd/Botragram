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
# Third Party
# =============================================================================
from dotenv import load_dotenv

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.env import (
    ENV_BOT_TOKEN,
    ENV_BOT_TOKEN_ALT,
    ENV_CHAT_ID,
    ENV_EXCHANGE_API_KEY,
    ENV_EXCHANGE_API_KEY_ALT,
    ENV_EXCHANGE_API_SECRET,
    ENV_EXCHANGE_API_SECRET_ALT,
    ENV_LOG_LEVEL,
    ENV_LOG_LEVEL_ALT,
    ENV_TRADE_MODE,
    ENV_TRADE_MODE_ALT,
)


# =============================================================================
# Provider Class
# =============================================================================
class EnvironmentProvider:
    """Provides access to environment variables loaded from .env."""

    def __init__(self, env_path: str = ".env") -> None:
        """Initialize provider and load environment variables.

        Args:
            env_path: File path to .env file.
        """
        load_dotenv(dotenv_path=env_path)

    def _get_var(self, primary_key: str, alt_key: str = "", default: str = "") -> str:
        """Helper to retrieve environment variable with fallback key.

        Args:
            primary_key: Primary environment variable name.
            alt_key: Alternative/legacy environment variable name.
            default: Default value if not set.

        Returns:
            Environment variable string value.
        """
        val = os.getenv(primary_key)
        if val is not None and val.strip():
            return val.strip()
        if alt_key:
            alt_val = os.getenv(alt_key)
            if alt_val is not None and alt_val.strip():
                return alt_val.strip()
        return default

    def get_bot_token(self) -> str:
        """Retrieve Telegram bot token.

        Returns:
            Bot token string.
        """
        return self._get_var(ENV_BOT_TOKEN, ENV_BOT_TOKEN_ALT)

    def get_chat_id(self) -> str:
        """Retrieve Telegram chat ID.

        Returns:
            Chat ID string.
        """
        return self._get_var(ENV_CHAT_ID)

    def get_api_key(self) -> str:
        """Retrieve Exchange API key.

        Returns:
            API key string.
        """
        return self._get_var(ENV_EXCHANGE_API_KEY, ENV_EXCHANGE_API_KEY_ALT)

    def get_api_secret(self) -> str:
        """Retrieve Exchange API secret.

        Returns:
            API secret string.
        """
        return self._get_var(ENV_EXCHANGE_API_SECRET, ENV_EXCHANGE_API_SECRET_ALT)

    def get_trade_mode(self) -> str:
        """Retrieve trade execution mode string.

        Returns:
            Trade mode string (PAPER/LIVE).
        """
        return self._get_var(ENV_TRADE_MODE, ENV_TRADE_MODE_ALT, default="PAPER")

    def get_log_level(self) -> str:
        """Retrieve log level string.

        Returns:
            Log level string (INFO/DEBUG/etc.).
        """
        return self._get_var(ENV_LOG_LEVEL, ENV_LOG_LEVEL_ALT, default="INFO")
