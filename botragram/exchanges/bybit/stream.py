"""
Botragram

Description:
    Bybit WebSocket stream client implementation.

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
# Bybit Stream Client Class
# =============================================================================
class BybitStreamClient(BaseStreamClient):
    """Bybit WebSocket public/private stream client."""

    def __init__(self, testnet: bool = True, category: str = "linear") -> None:
        """Initialize Bybit WebSocket stream client.

        Args:
            testnet: Use Bybit testnet stream if True.
            category: Stream category (linear, spot, etc.).
        """
        domain = "stream-testnet.bybit.com" if testnet else "stream.bybit.com"
        ws_url = f"wss://{domain}/v5/public/{category}"
        super().__init__(ws_url=ws_url)
