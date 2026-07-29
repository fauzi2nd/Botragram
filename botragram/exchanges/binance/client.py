"""
Botragram

Description:
    Binance exchange client.

Python:
    3.14+
"""

from __future__ import annotations


class BinanceClient:
    """Concrete client for the Binance exchange."""

    def __init__(self) -> None:
        self.exchange_name = "binance"
