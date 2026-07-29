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
    ENV_BINANCE_API_KEY,
    ENV_BINANCE_API_SECRET,
    ENV_BINANCE_TESTNET,
    ENV_BITGET_API_KEY,
    ENV_BITGET_API_SECRET,
    ENV_BITGET_PASSPHRASE,
    ENV_BITGET_TESTNET,
    ENV_BOT_TOKEN,
    ENV_BOT_TOKEN_ALT,
    ENV_BYBIT_API_KEY,
    ENV_BYBIT_API_SECRET,
    ENV_BYBIT_TESTNET,
    ENV_CHAT_ID,
    ENV_EXCHANGE,
    ENV_EXCHANGE_API_KEY,
    ENV_EXCHANGE_API_KEY_ALT,
    ENV_EXCHANGE_API_SECRET,
    ENV_EXCHANGE_API_SECRET_ALT,
    ENV_LOG_LEVEL,
    ENV_LOG_LEVEL_ALT,
    ENV_OKX_API_KEY,
    ENV_OKX_API_SECRET,
    ENV_OKX_PASSPHRASE,
    ENV_OKX_TESTNET,
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
        """Retrieve environment variable with optional fallback key.

        Args:
            primary_key: Primary environment variable name.
            alt_key: Alternative/legacy variable name.
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

    def _get_bool(self, key: str, default: bool = True) -> bool:
        """Retrieve boolean environment variable.

        Args:
            key: Environment variable name.
            default: Default boolean value.

        Returns:
            Boolean value.
        """
        val = os.getenv(key, "").strip().lower()
        if val in ("false", "0", "no"):
            return False
        if val in ("true", "1", "yes"):
            return True
        return default

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------

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

    def get_active_exchange(self) -> str:
        """Retrieve active exchange selection from env.

        Returns:
            Exchange name string (BYBIT/BINANCE/OKX/BITGET).
        """
        return self._get_var(ENV_EXCHANGE, default="BYBIT").upper()

    # -------------------------------------------------------------------------
    # Bybit
    # -------------------------------------------------------------------------

    def get_bybit_api_key(self) -> str:
        """Retrieve Bybit API key.

        Returns:
            API key string.
        """
        return self._get_var(ENV_BYBIT_API_KEY, ENV_EXCHANGE_API_KEY, "")

    def get_bybit_api_secret(self) -> str:
        """Retrieve Bybit API secret.

        Returns:
            API secret string.
        """
        return self._get_var(ENV_BYBIT_API_SECRET, ENV_EXCHANGE_API_SECRET, "")

    def get_bybit_testnet(self) -> bool:
        """Retrieve Bybit testnet flag.

        Returns:
            True if testnet, False if mainnet.
        """
        return self._get_bool(ENV_BYBIT_TESTNET, default=True)

    # -------------------------------------------------------------------------
    # Binance
    # -------------------------------------------------------------------------

    def get_binance_api_key(self) -> str:
        """Retrieve Binance API key.

        Returns:
            API key string.
        """
        return self._get_var(ENV_BINANCE_API_KEY, ENV_EXCHANGE_API_KEY_ALT, "")

    def get_binance_api_secret(self) -> str:
        """Retrieve Binance API secret.

        Returns:
            API secret string.
        """
        return self._get_var(ENV_BINANCE_API_SECRET, ENV_EXCHANGE_API_SECRET_ALT, "")

    def get_binance_testnet(self) -> bool:
        """Retrieve Binance testnet flag.

        Returns:
            True if testnet, False if mainnet.
        """
        return self._get_bool(ENV_BINANCE_TESTNET, default=True)

    # -------------------------------------------------------------------------
    # OKX
    # -------------------------------------------------------------------------

    def get_okx_api_key(self) -> str:
        """Retrieve OKX API key.

        Returns:
            API key string.
        """
        return self._get_var(ENV_OKX_API_KEY)

    def get_okx_api_secret(self) -> str:
        """Retrieve OKX API secret.

        Returns:
            API secret string.
        """
        return self._get_var(ENV_OKX_API_SECRET)

    def get_okx_passphrase(self) -> str:
        """Retrieve OKX API passphrase.

        Returns:
            Passphrase string.
        """
        return self._get_var(ENV_OKX_PASSPHRASE)

    def get_okx_testnet(self) -> bool:
        """Retrieve OKX testnet flag.

        Returns:
            True if testnet, False if mainnet.
        """
        return self._get_bool(ENV_OKX_TESTNET, default=True)

    # -------------------------------------------------------------------------
    # Bitget
    # -------------------------------------------------------------------------

    def get_bitget_api_key(self) -> str:
        """Retrieve Bitget API key.

        Returns:
            API key string.
        """
        return self._get_var(ENV_BITGET_API_KEY)

    def get_bitget_api_secret(self) -> str:
        """Retrieve Bitget API secret.

        Returns:
            API secret string.
        """
        return self._get_var(ENV_BITGET_API_SECRET)

    def get_bitget_passphrase(self) -> str:
        """Retrieve Bitget API passphrase.

        Returns:
            Passphrase string.
        """
        return self._get_var(ENV_BITGET_PASSPHRASE)

    def get_bitget_testnet(self) -> bool:
        """Retrieve Bitget testnet flag.

        Returns:
            True if testnet, False if mainnet.
        """
        return self._get_bool(ENV_BITGET_TESTNET, default=True)

    # -------------------------------------------------------------------------
    # Legacy generic getters (backward compatibility)
    # -------------------------------------------------------------------------

    def get_api_key(self) -> str:
        """Retrieve API key for active exchange.

        Returns:
            API key string.
        """
        exchange = self.get_active_exchange()
        if exchange == "BINANCE":
            return self.get_binance_api_key()
        if exchange == "OKX":
            return self.get_okx_api_key()
        if exchange == "BITGET":
            return self.get_bitget_api_key()
        return self.get_bybit_api_key()

    def get_api_secret(self) -> str:
        """Retrieve API secret for active exchange.

        Returns:
            API secret string.
        """
        exchange = self.get_active_exchange()
        if exchange == "BINANCE":
            return self.get_binance_api_secret()
        if exchange == "OKX":
            return self.get_okx_api_secret()
        if exchange == "BITGET":
            return self.get_bitget_api_secret()
        return self.get_bybit_api_secret()
