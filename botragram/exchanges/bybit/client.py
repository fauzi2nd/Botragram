"""
Botragram

Description:
    Unified Bybit exchange client implementation.

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
import logging

# =============================================================================
# Local Imports
# =============================================================================
from botragram.exchanges.base.client import BaseExchangeClient

logger = logging.getLogger(__name__)


# =============================================================================
# Client Class
# =============================================================================
class BybitClient(BaseExchangeClient):
    """Unified client for interacting with Bybit REST and WebSocket APIs."""
