"""
Botragram

Description:
    Exchange settings model.

Python:
    3.14+
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ExchangeSettings:
    """Exchange settings container."""

    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
