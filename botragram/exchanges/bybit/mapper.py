"""
Botragram

Description:
    Bybit exchange data mapper implementation.

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
# =============================================================================
# Local Imports
# =============================================================================
from botragram.exchanges.base.mapper import BaseExchangeMapper


# =============================================================================
# Mapper Implementation Class
# =============================================================================
class BybitMapper(BaseExchangeMapper):
    """Data mapper for converting Bybit API payloads to standard models."""
