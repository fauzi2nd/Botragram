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
from botragram.enums.account_type import AccountType
from botragram.enums.ai_model_type import AiModelType
from botragram.enums.ai_provider import AiProvider
from botragram.enums.base import BaseEnum
from botragram.enums.environment import Environment
from botragram.enums.exchange_type import ExchangeType
from botragram.enums.indicator_type import IndicatorType
from botragram.enums.interval import Interval
from botragram.enums.leverage_mode import LeverageMode
from botragram.enums.log_level import LogLevel
from botragram.enums.margin_mode import MarginMode
from botragram.enums.market_type import MarketType
from botragram.enums.notification_type import NotificationType
from botragram.enums.order_side import OrderSide
from botragram.enums.order_status import OrderStatus
from botragram.enums.order_type import OrderType
from botragram.enums.position_side import PositionSide
from botragram.enums.position_status import PositionStatus
from botragram.enums.signal_type import SignalType
from botragram.enums.strategy_type import StrategyType
from botragram.enums.telegram_state import TelegramState
from botragram.enums.time_in_force import TimeInForce
from botragram.enums.trade_mode import TradeMode
from botragram.enums.trend_type import TrendType

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    # Base
    "BaseEnum",
    # AI
    "AiProvider",
    "AiModelType",
    # Environment
    "Environment",
    # Exchange
    "ExchangeType",
    "MarketType",
    "AccountType",
    "TradeMode",
    "MarginMode",
    "LeverageMode",
    # Market
    "Interval",
    "TrendType",
    "IndicatorType",
    # Trading
    "OrderType",
    "OrderSide",
    "OrderStatus",
    "TimeInForce",
    "PositionSide",
    "PositionStatus",
    "SignalType",
    "StrategyType",
    # Application
    "NotificationType",
    "TelegramState",
    "LogLevel",
]
