"""
Botragram

Description:
    Binance REST API client implementation.

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
import logging
from typing import Any

# =============================================================================
# Local Imports
# =============================================================================
from botragram.exchanges.base.rest import BaseRestClient

logger = logging.getLogger(__name__)


# =============================================================================
# Binance REST Client Class
# =============================================================================
class BinanceRestClient(BaseRestClient):
    """Binance REST API client implementation."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
    ) -> None:
        """Initialize Binance REST API client.

        Args:
            api_key: Binance API key.
            api_secret: Binance API secret.
            testnet: Use Binance testnet if True.
        """
        base_url = (
            "https://testnet.binancefuture.com"
            if testnet
            else "https://fapi.binance.com"
        )
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            api_secret=api_secret,
        )

    async def get_ticker_24hr(self, symbol: str = "") -> Any:
        """Fetch 24hr ticker price change statistics.

        Args:
            symbol: Optional symbol filter string.

        Returns:
            JSON response dictionary.
        """
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v1/ticker/24hr", params=params)

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
    ) -> Any:
        """Fetch candlestick kline data.

        Args:
            symbol: Symbol string.
            interval: Timeframe interval string (e.g. 1m, 1h).
            limit: Candle count limit.

        Returns:
            JSON response dictionary or list.
        """
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        return await self._request("GET", "/fapi/v1/klines", params=params)
