"""
Botragram

Description:
    Environment variable key constants.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Constants — Application
# =============================================================================
ENV_BOT_TOKEN: str = "TELEGRAM_TOKEN"
ENV_BOT_TOKEN_ALT: str = "BOTRAGRAM_TELEGRAM_TOKEN"
ENV_CHAT_ID: str = "TELEGRAM_CHAT_ID"
ENV_TRADE_MODE: str = "TRADE_MODE"
ENV_TRADE_MODE_ALT: str = "BOTRAGRAM_TRADE_MODE"
ENV_LOG_LEVEL: str = "LOG_LEVEL"
ENV_LOG_LEVEL_ALT: str = "BOTRAGRAM_LOG_LEVEL"

# =============================================================================
# Constants — Active Exchange Selection
# =============================================================================
ENV_EXCHANGE: str = "EXCHANGE"

# =============================================================================
# Constants — Bybit
# =============================================================================
ENV_BYBIT_API_KEY: str = "BYBIT_API_KEY"
ENV_BYBIT_API_SECRET: str = "BYBIT_API_SECRET"
ENV_BYBIT_TESTNET: str = "BYBIT_TESTNET"

# =============================================================================
# Constants — Binance
# =============================================================================
ENV_BINANCE_API_KEY: str = "BINANCE_API_KEY"
ENV_BINANCE_API_SECRET: str = "BINANCE_API_SECRET"
ENV_BINANCE_TESTNET: str = "BINANCE_TESTNET"

# =============================================================================
# Constants — OKX
# =============================================================================
ENV_OKX_API_KEY: str = "OKX_API_KEY"
ENV_OKX_API_SECRET: str = "OKX_API_SECRET"
ENV_OKX_PASSPHRASE: str = "OKX_PASSPHRASE"
ENV_OKX_TESTNET: str = "OKX_TESTNET"

# =============================================================================
# Constants — Bitget
# =============================================================================
ENV_BITGET_API_KEY: str = "BITGET_API_KEY"
ENV_BITGET_API_SECRET: str = "BITGET_API_SECRET"
ENV_BITGET_PASSPHRASE: str = "BITGET_PASSPHRASE"
ENV_BITGET_TESTNET: str = "BITGET_TESTNET"

# =============================================================================
# Legacy fallback keys (kept for backward compatibility)
# =============================================================================
ENV_EXCHANGE_API_KEY: str = "EXCHANGE_API_KEY"
ENV_EXCHANGE_API_KEY_ALT: str = "BOTRAGRAM_EXCHANGE_API_KEY"
ENV_EXCHANGE_API_SECRET: str = "EXCHANGE_API_SECRET"
ENV_EXCHANGE_API_SECRET_ALT: str = "BOTRAGRAM_EXCHANGE_API_SECRET"
