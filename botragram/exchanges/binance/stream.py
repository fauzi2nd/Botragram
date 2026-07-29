"""
Botragram

Description:
    Binance WebSocket stream client implementation.

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
from botragram.exchanges.base.stream import BaseStreamClient


# =============================================================================
# Binance Stream Client Class
# =============================================================================
class BinanceStreamClient(BaseStreamClient):
    """Binance WebSocket stream client."""

    def __init__(self, testnet: bool = True) -> None:
        """Initialize Binance WebSocket stream client.

        Args:
            testnet: Use Binance testnet stream if True.
        """
        domain = (
            "stream.binancefuture.com"
            if testnet
            else "fstream.binance.com"
        )
        ws_url = f"wss://{domain}/ws"
        super().__init__(ws_url=ws_url)
