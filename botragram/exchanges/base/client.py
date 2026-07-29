"""
Botragram

Description:
    Base exchange client protocol and abstract base class.

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
from abc import ABC, abstractmethod
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.interval import Interval
from botragram.enums.order_side import OrderSide
from botragram.enums.order_type import OrderType
from botragram.exchanges.base.mapper import (
    Candle,
    OrderResult,
    PositionInfo,
    Ticker,
)


# =============================================================================
# Abstract Base Client Class
# =============================================================================
class BaseExchangeClient(ABC):
    """Abstract Base Class for crypto exchange clients."""

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Fetch latest price ticker for symbol.

        Args:
            symbol: Trading pair symbol (e.g. BTCUSDT).

        Returns:
            Standardized Ticker instance.
        """

    @abstractmethod
    async def fetch_candles(
        self,
        symbol: str,
        interval: Interval,
        limit: int = 100,
    ) -> list[Candle]:
        """Fetch historical candlestick OHLCV data.

        Args:
            symbol: Trading pair symbol.
            interval: Timeframe interval enum.
            limit: Number of candles to retrieve.

        Returns:
            List of standardized Candle instances.
        """

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> OrderResult:
        """Submit a new trading order.

        Args:
            symbol: Trading pair symbol.
            side: Order side enum (BUY/SELL).
            order_type: Order type enum (LIMIT/MARKET).
            quantity: Order quantity as Decimal.
            price: Optional order price for LIMIT orders.

        Returns:
            Standardized OrderResult instance.
        """

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an active order.

        Args:
            symbol: Trading pair symbol.
            order_id: Exchange order ID string.

        Returns:
            True if cancelled successfully, False otherwise.
        """

    @abstractmethod
    async def fetch_positions(
        self,
        symbol: str | None = None,
    ) -> list[PositionInfo]:
        """Fetch active positions info.

        Args:
            symbol: Optional symbol filter.

        Returns:
            List of PositionInfo instances.
        """

    @abstractmethod
    async def close(self) -> None:
        """Close underlying HTTP sessions and WebSocket streams."""
