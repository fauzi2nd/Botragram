"""
Botragram

Description:
    Explicit placeholder for the unavailable Bybit stream transport.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from collections.abc import AsyncIterator

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.exchanges.base.stream import BaseStreamClient
from botragram.models import Candle, Ticker

__all__ = [
    "BybitStreamClient",
]


# =============================================================================
# Constants
# =============================================================================
_NOT_IMPLEMENTED_ERROR = "Bybit stream transport is not implemented"


# =============================================================================
# Bybit Stream Client
# =============================================================================
class BybitStreamClient(BaseStreamClient):
    """Represent the reserved Bybit streaming integration point."""

    __slots__ = ()

    @property
    def is_connected(self) -> bool:
        """Return false because the placeholder cannot connect."""
        return False

    async def connect(self) -> None:
        """Reject connection until the Bybit stream is implemented."""
        raise NotImplementedError(_NOT_IMPLEMENTED_ERROR)

    def stream_ticker(
        self,
        *,
        symbol: str,
    ) -> AsyncIterator[Ticker]:
        """Reject ticker streaming until the transport is implemented."""
        del symbol
        raise NotImplementedError(_NOT_IMPLEMENTED_ERROR)

    def stream_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
    ) -> AsyncIterator[Candle]:
        """Reject candle streaming until the transport is implemented."""
        del symbol, interval
        raise NotImplementedError(_NOT_IMPLEMENTED_ERROR)

    async def unsubscribe(
        self,
        *,
        symbol: str,
    ) -> None:
        """Reject unsubscribe until the transport is implemented."""
        del symbol
        raise NotImplementedError(_NOT_IMPLEMENTED_ERROR)

    async def close(self) -> None:
        """Close the placeholder stream without side effects."""
