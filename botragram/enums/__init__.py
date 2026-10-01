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
from botragram.enums.account.live_futures_user_data_status import (
    LiveFuturesUserDataStatus,
)
from botragram.enums.ai.ai_model_type import AiModelType
from botragram.enums.ai.ai_provider import AiProvider
from botragram.enums.base import BaseEnum
from botragram.enums.cfd.cfd_instrument_status import CfdInstrumentStatus
from botragram.enums.discovery.global_discovery_cycle_outcome import (
    GlobalDiscoveryCycleOutcome,
)
from botragram.enums.discovery.global_discovery_cycle_state import (
    GlobalDiscoveryCycleState,
)
from botragram.enums.execution.authorization_status import AuthorizationStatus
from botragram.enums.execution.autonomous_live_entry_execution_status import (
    AutonomousLiveEntryExecutionStatus,
)
from botragram.enums.execution.autonomous_live_entry_intent_status import (
    AutonomousLiveEntryIntentStatus,
)
from botragram.enums.execution.execution_policy import ExecutionPolicy
from botragram.enums.execution.futures_algo_order_status import FuturesAlgoOrderStatus
from botragram.enums.execution.margin_mode import MarginMode
from botragram.enums.execution.order_side import OrderSide
from botragram.enums.execution.order_status import OrderStatus
from botragram.enums.execution.order_type import OrderType
from botragram.enums.execution.signal_type import SignalType
from botragram.enums.execution.submission_attempt_status import SubmissionAttemptStatus
from botragram.enums.execution.trade_mode import TradeMode
from botragram.enums.log_level import LogLevel
from botragram.enums.market.asset_class import AssetClass
from botragram.enums.market.exchange_environment import ExchangeEnvironment
from botragram.enums.market.exchange_type import ExchangeType
from botragram.enums.market.interval import Interval
from botragram.enums.market.live_market_stream_lifecycle_status import (
    LiveMarketStreamLifecycleStatus,
)
from botragram.enums.market.market_session_status import MarketSessionStatus
from botragram.enums.market.market_type import MarketType
from botragram.enums.market.open_interest_regime import OpenInterestRegime
from botragram.enums.notification_type import NotificationType
from botragram.enums.position.closed_position_provenance import ClosedPositionProvenance
from botragram.enums.position.closed_position_reason import ClosedPositionReason
from botragram.enums.position.operator_exit_attempt_status import (
    OperatorExitAttemptStatus,
)
from botragram.enums.position.operator_exit_status import OperatorExitStatus
from botragram.enums.position.operator_exit_type import OperatorExitType
from botragram.enums.position.position_exit_action import PositionExitAction
from botragram.enums.position.position_side import PositionSide
from botragram.enums.position.trailing_mode import TrailingMode
from botragram.enums.recovery.autonomous_live_recovery_reason import (
    AutonomousLiveRecoveryReason,
)
from botragram.enums.recovery.autonomous_live_recovery_status import (
    AutonomousLiveRecoveryStatus,
)
from botragram.enums.recovery.live_portfolio_recovery_status import (
    LivePortfolioRecoveryStatus,
)
from botragram.enums.recovery.live_portfolio_recovery_unsafe_reason import (
    LivePortfolioRecoveryUnsafeReason,
)
from botragram.enums.runtime.environment import Environment
from botragram.enums.runtime.environment_profile import EnvironmentProfile
from botragram.enums.runtime.live_runtime_health_reason import LiveRuntimeHealthReason
from botragram.enums.runtime.live_runtime_health_status import LiveRuntimeHealthStatus
from botragram.enums.strategy.stalking_status import StalkingStatus
from botragram.enums.strategy.strategy_type import StrategyType

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
    "ClosedPositionProvenance",
    "ClosedPositionReason",
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
    "MarginMode",
    "MarketType",
    "TradeMode",
    "LiveMarketStreamLifecycleStatus",
    "LiveFuturesUserDataStatus",
    "LiveRuntimeHealthReason",
    "LiveRuntimeHealthStatus",
    "LivePortfolioRecoveryStatus",
    "LivePortfolioRecoveryUnsafeReason",
    # Market
    "AssetClass",
    "CfdInstrumentStatus",
    "Interval",
    "MarketSessionStatus",
    "OpenInterestRegime",
    # Trading
    "OrderType",
    "OrderSide",
    "OrderStatus",
    "OperatorExitAttemptStatus",
    "OperatorExitStatus",
    "OperatorExitType",
    "PositionExitAction",
    "PositionSide",
    "SignalType",
    "StalkingStatus",
    "StrategyType",
    "SubmissionAttemptStatus",
    "TrailingMode",
    # Application
    "NotificationType",
    "LogLevel",
]
