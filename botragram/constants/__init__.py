"""
Botragram

Description:
    Constants package initialization.

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
from botragram.constants.app import APP_NAME, APP_VERSION, DEFAULT_ENCODING
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
from botragram.constants.exchange import (
    DEFAULT_CANDLE_FETCH_LIMIT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_RETRY_DELAY_SECONDS,
    DEFAULT_WS_RECONNECT_DELAY_SECONDS,
)
from botragram.constants.market import (
    DEFAULT_MAKER_FEE_RATE,
    DEFAULT_PRICE_PRECISION,
    DEFAULT_QTY_PRECISION,
    DEFAULT_TAKER_FEE_RATE,
)
from botragram.constants.telegram import (
    CMD_POSITIONS,
    CMD_SETTINGS,
    CMD_START,
    CMD_STATUS,
    CMD_STOP,
    DEFAULT_PARSE_MODE,
)
from botragram.constants.time import (
    DISPLAY_DATETIME_FORMAT,
    ISO_DATETIME_FORMAT,
    SECONDS_IN_DAY,
    SECONDS_IN_HOUR,
    SECONDS_IN_MINUTE,
)

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "CMD_POSITIONS",
    "CMD_SETTINGS",
    "CMD_START",
    "CMD_STATUS",
    "CMD_STOP",
    "DEFAULT_CANDLE_FETCH_LIMIT",
    "DEFAULT_ENCODING",
    "DEFAULT_MAKER_FEE_RATE",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_PARSE_MODE",
    "DEFAULT_PRICE_PRECISION",
    "DEFAULT_QTY_PRECISION",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "DEFAULT_RETRY_DELAY_SECONDS",
    "DEFAULT_TAKER_FEE_RATE",
    "DEFAULT_WS_RECONNECT_DELAY_SECONDS",
    "DISPLAY_DATETIME_FORMAT",
    "ENV_BOT_TOKEN",
    "ENV_BOT_TOKEN_ALT",
    "ENV_CHAT_ID",
    "ENV_EXCHANGE_API_KEY",
    "ENV_EXCHANGE_API_KEY_ALT",
    "ENV_EXCHANGE_API_SECRET",
    "ENV_EXCHANGE_API_SECRET_ALT",
    "ENV_LOG_LEVEL",
    "ENV_LOG_LEVEL_ALT",
    "ENV_TRADE_MODE",
    "ENV_TRADE_MODE_ALT",
    "ISO_DATETIME_FORMAT",
    "SECONDS_IN_DAY",
    "SECONDS_IN_HOUR",
    "SECONDS_IN_MINUTE",
]
