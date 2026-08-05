"""
Botragram

Description:
    Repository interfaces package initialization.

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
from botragram.repositories.candle_repository import CandleRepository
from botragram.repositories.order_repository import OrderRepository
from botragram.repositories.position_repository import PositionRepository
from botragram.repositories.signal_repository import SignalRepository
from botragram.repositories.trade_repository import TradeRepository

__all__ = [
    "CandleRepository",
    "SignalRepository",
    "OrderRepository",
    "TradeRepository",
    "PositionRepository",
]
