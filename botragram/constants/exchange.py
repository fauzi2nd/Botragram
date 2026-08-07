"""
Botragram

Description:
    Exchange default configurations and constants.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

__all__ = [
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_DELAY_SECONDS",
    "DEFAULT_WS_RECONNECT_DELAY_SECONDS",
    "DEFAULT_RECV_WINDOW_MS",
    "DEFAULT_CANDLE_FETCH_LIMIT",
    "BINANCE_REST_BASE_URL",
    "BINANCE_TESTNET_REST_BASE_URL",
    "BINANCE_WEBSOCKET_BASE_URL",
    "BINANCE_TESTNET_WEBSOCKET_BASE_URL",
    "BINANCE_FUTURES_REST_BASE_URL",
    "BINANCE_FUTURES_TESTNET_REST_BASE_URL",
    "BINANCE_FUTURES_WEBSOCKET_BASE_URL",
    "BINANCE_FUTURES_TESTNET_WEBSOCKET_BASE_URL",
]

# =============================================================================
# HTTP
# =============================================================================
DEFAULT_REQUEST_TIMEOUT_SECONDS: float = 10.0

DEFAULT_MAX_RETRIES: int = 3

DEFAULT_RETRY_DELAY_SECONDS: float = 1.0

# =============================================================================
# WebSocket
# =============================================================================
DEFAULT_WS_RECONNECT_DELAY_SECONDS: float = 5.0

# =============================================================================
# Exchange
# =============================================================================
DEFAULT_RECV_WINDOW_MS: int = 5_000

DEFAULT_CANDLE_FETCH_LIMIT: int = 100

# =============================================================================
# Binance URLs
# =============================================================================
BINANCE_REST_BASE_URL: str = "https://api.binance.com"
BINANCE_TESTNET_REST_BASE_URL: str = "https://testnet.binance.vision"
BINANCE_WEBSOCKET_BASE_URL: str = "wss://stream.binance.com:9443"
BINANCE_TESTNET_WEBSOCKET_BASE_URL: str = "wss://stream.testnet.binance.vision"

BINANCE_FUTURES_REST_BASE_URL: str = "https://fapi.binance.com"
BINANCE_FUTURES_TESTNET_REST_BASE_URL: str = "https://demo-fapi.binance.com"
BINANCE_FUTURES_WEBSOCKET_BASE_URL: str = "wss://fstream.binance.com/market"
BINANCE_FUTURES_TESTNET_WEBSOCKET_BASE_URL: str = (
    "wss://demo-fstream.binance.com/market"
)
