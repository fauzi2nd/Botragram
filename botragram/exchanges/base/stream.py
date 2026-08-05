"""
Botragram

Description:
    Base exchange streaming client interface.

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
from collections.abc import AsyncIterator

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.interval import Interval
from botragram.models import Candle, Ticker

__all__ = [
    "BaseStreamClient",
]


# =============================================================================
# Abstract Base Stream Client
# =============================================================================
class BaseStreamClient(ABC):
    """Abstract interface for exchange streaming clients."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return whether the streaming connection is active."""

    @abstractmethod
    async def connect(self) -> None:
        """Open the exchange streaming connection."""

    @abstractmethod
    def stream_ticker(
        self,
        *,
        symbol: str,
    ) -> AsyncIterator[Ticker]:
        """Stream ticker updates for a trading symbol.

        Args:
            symbol: Trading pair symbol.

        Returns:
            Asynchronous iterator yielding standardized ticker models.
        """

    @abstractmethod
    def stream_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
    ) -> AsyncIterator[Candle]:
        """Stream candlestick updates for a trading symbol.

        Args:
            symbol: Trading pair symbol.
            interval: Candlestick timeframe.

        Returns:
            Asynchronous iterator yielding standardized candle models.
        """

    @abstractmethod
    async def unsubscribe(
        self,
        *,
        symbol: str,
    ) -> None:
        """Remove all active subscriptions for a symbol.

        Args:
            symbol: Trading pair symbol.
        """

    @abstractmethod
    async def close(self) -> None:
        """Close the streaming connection and release its resources."""
