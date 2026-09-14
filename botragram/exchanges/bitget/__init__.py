"""
Botragram

Description:
    Bitget exchange connector package.

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
from botragram.exchanges.bitget.client import BITGET_INTERVAL_MAP, BitgetClient
from botragram.exchanges.bitget.futures_client import BitgetFuturesExchangeClient
from botragram.exchanges.bitget.mapper import BitgetExchangeMapper, BitgetMapper
from botragram.exchanges.bitget.rest import BitgetRestClient, BitgetRestResponseError
from botragram.exchanges.bitget.stream import BitgetStreamClient

__all__ = [
    "BITGET_INTERVAL_MAP",
    "BitgetClient",
    "BitgetExchangeMapper",
    "BitgetFuturesExchangeClient",
    "BitgetMapper",
    "BitgetRestClient",
    "BitgetRestResponseError",
    "BitgetStreamClient",
]
