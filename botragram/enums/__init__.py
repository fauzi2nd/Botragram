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
from botragram.enums.authorization_status import AuthorizationStatus
from botragram.enums.autonomous_live_entry_execution_status import (
    AutonomousLiveEntryExecutionStatus,
)
from botragram.enums.autonomous_live_entry_intent_status import (
    AutonomousLiveEntryIntentStatus,
)
from botragram.enums.autonomous_live_recovery_reason import AutonomousLiveRecoveryReason
from botragram.enums.autonomous_live_recovery_status import AutonomousLiveRecoveryStatus
from botragram.enums.base import BaseEnum
from botragram.enums.environment import Environment
from botragram.enums.environment_profile import EnvironmentProfile
from botragram.enums.exchange_environment import ExchangeEnvironment
from botragram.enums.exchange_type import ExchangeType
from botragram.enums.execution_policy import ExecutionPolicy
from botragram.enums.futures_algo_order_status import FuturesAlgoOrderStatus
from botragram.enums.global_discovery_cycle_outcome import GlobalDiscoveryCycleOutcome
from botragram.enums.global_discovery_cycle_state import GlobalDiscoveryCycleState
from botragram.enums.indicator_type import IndicatorType
from botragram.enums.interval import Interval
from botragram.enums.leverage_mode import LeverageMode
from botragram.enums.live_futures_user_data_status import (
    LiveFuturesUserDataStatus,
)
from botragram.enums.live_market_stream_lifecycle_status import (
    LiveMarketStreamLifecycleStatus,
)
from botragram.enums.live_portfolio_recovery_status import (
    LivePortfolioRecoveryStatus,
)
from botragram.enums.live_portfolio_recovery_unsafe_reason import (
    LivePortfolioRecoveryUnsafeReason,
)
from botragram.enums.live_runtime_health_reason import LiveRuntimeHealthReason
from botragram.enums.live_runtime_health_status import LiveRuntimeHealthStatus
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
from botragram.enums.submission_attempt_status import SubmissionAttemptStatus
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
    "AuthorizationStatus",
    "AutonomousLiveEntryExecutionStatus",
    "AutonomousLiveEntryIntentStatus",
    "AutonomousLiveRecoveryReason",
    "AutonomousLiveRecoveryStatus",
    # Environment
    "Environment",
    "EnvironmentProfile",
    "ExchangeEnvironment",
    "ExecutionPolicy",
    "GlobalDiscoveryCycleOutcome",
    "GlobalDiscoveryCycleState",
    "FuturesAlgoOrderStatus",
    # Exchange
    "ExchangeType",
    "MarketType",
    "AccountType",
    "TradeMode",
    "MarginMode",
    "LeverageMode",
    "LiveMarketStreamLifecycleStatus",
    "LiveFuturesUserDataStatus",
    "LiveRuntimeHealthReason",
    "LiveRuntimeHealthStatus",
    "LivePortfolioRecoveryStatus",
    "LivePortfolioRecoveryUnsafeReason",
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
    "SubmissionAttemptStatus",
    # Application
    "NotificationType",
    "TelegramState",
    "LogLevel",
]
