"""
Botragram

Description:
    TradFi CFD instrument tradability status enumeration.

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
from enum import StrEnum

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "CfdInstrumentStatus",
]


# =============================================================================
# CFD Instrument Status Enum
# =============================================================================
class CfdInstrumentStatus(StrEnum):
    """Trading availability status for CFD instruments."""

    DISABLED = "disabled"  # enable=0: Trading completely disabled
    CLOSE_ONLY = "close_only"  # enable=1: Close-position only
    TRADING_ALLOWED = "trading_allowed"  # enable=2: Full trading allowed
