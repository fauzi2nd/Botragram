"""
Botragram

Description:
    Canonical exchange network environment choices.

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
from botragram.enums.base import BaseEnum

__all__ = ["ExchangeEnvironment"]


# =============================================================================
# Enums
# =============================================================================
class ExchangeEnvironment(BaseEnum):
    """Select the network used by an exchange connection."""

    TESTNET = "testnet"
    MAINNET = "mainnet"
