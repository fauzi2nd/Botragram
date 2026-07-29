"""
Botragram

Description:
    Bybit REST API client implementation.

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
# Bybit REST Client Class
# =============================================================================
class BybitRestClient(BaseRestClient):
    """Bybit v5 REST API client implementation."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
    ) -> None:
        """Initialize Bybit REST API client.

        Args:
            api_key: Bybit API key.
            api_secret: Bybit API secret.
            testnet: Use Bybit testnet if True.
        """
        base_url = (
            "https://api-testnet.bybit.com"
            if testnet
            else "https://api.bybit.com"
        )
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            api_secret=api_secret,
        )

    async def get_tickers(self, category: str = "linear", symbol: str = "") -> Any:
        """Fetch market ticker information.

        Args:
            category: Product category (linear, spot, etc.).
            symbol: Optional symbol filter.

        Returns:
            JSON response dictionary.
        """
        params: dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/v5/market/tickers", params=params)

    async def get_kline(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
        category: str = "linear",
    ) -> Any:
        """Fetch candlestick kline data.

        Args:
            symbol: Symbol name string.
            interval: Timeframe interval string.
            limit: Candle count limit.
            category: Product category string.

        Returns:
            JSON response dictionary.
        """
        params: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        return await self._request("GET", "/v5/market/kline", params=params)
