"""
Botragram

Description:
    Base exchange package initialization.

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
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.base.mapper import (
    BaseExchangeMapper,
    Candle,
    OrderResult,
    PositionInfo,
    Ticker,
)
from botragram.exchanges.base.rest import BaseRestClient
from botragram.exchanges.base.stream import BaseStreamClient, StreamCallback

__all__ = [
    "BaseExchangeClient",
    "BaseExchangeMapper",
    "BaseRestClient",
    "BaseStreamClient",
    "Candle",
    "OrderResult",
    "PositionInfo",
    "StreamCallback",
    "Ticker",
]
