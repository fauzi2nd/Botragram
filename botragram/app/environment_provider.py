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
    ENV_EXCHANGE_API_KEY,
    ENV_EXCHANGE_API_SECRET,
    ENV_LOG_LEVEL,
    ENV_TRADE_MODE,
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

    def get_bot_token(self) -> str:
        """Retrieve Telegram bot token.

        Returns:
            Bot token string.
        """
        return os.getenv(ENV_BOT_TOKEN, "")

    def get_api_key(self) -> str:
        """Retrieve Exchange API key.

        Returns:
            API key string.
        """
        return os.getenv(ENV_EXCHANGE_API_KEY, "")

    def get_api_secret(self) -> str:
        """Retrieve Exchange API secret.

        Returns:
            API secret string.
        """
        return os.getenv(ENV_EXCHANGE_API_SECRET, "")

    def get_trade_mode(self) -> str:
        """Retrieve trade execution mode string.

        Returns:
            Trade mode string.
        """
        return os.getenv(ENV_TRADE_MODE, "PAPER")

    def get_log_level(self) -> str:
        """Retrieve log level string.

        Returns:
            Log level string.
        """
        return os.getenv(ENV_LOG_LEVEL, "INFO")
