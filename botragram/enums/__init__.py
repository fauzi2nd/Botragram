"""
Botragram

Description:
    Enums package initialization.

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
from botragram.enums.exchange_type import ExchangeType
from botragram.enums.interval import Interval
from botragram.enums.margin_mode import MarginMode
from botragram.enums.order_side import OrderSide
from botragram.enums.order_status import OrderStatus
from botragram.enums.order_type import OrderType
from botragram.enums.position_side import PositionSide
from botragram.enums.signal_type import SignalType
from botragram.enums.strategy_type import StrategyType
from botragram.enums.telegram_state import TelegramState
from botragram.enums.time_in_force import TimeInForce
from botragram.enums.trade_mode import TradeMode

__all__ = [
    "ExchangeType",
    "Interval",
    "MarginMode",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PositionSide",
    "SignalType",
    "StrategyType",
    "TelegramState",
    "TimeInForce",
    "TradeMode",
]
