"""
Botragram

Description:
    Domain models package initialization.

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
from botragram.models.account import Account
from botragram.models.backtest import (
    BacktestMetrics,
    BacktestRequest,
    BacktestResult,
    BacktestTrade,
)
from botragram.models.balance import Balance
from botragram.models.candle import Candle
from botragram.models.execution_authorization import (
    ExecutionAuthorization,
    ExecutionAuthorizationOutcome,
)
from botragram.models.notification import Notification
from botragram.models.order import Order
from botragram.models.position import Position
from botragram.models.risk import (
    PositionSize,
    RiskMetrics,
    RiskResult,
)
from botragram.models.signal import Signal
from botragram.models.submission_attempt import SubmissionAttempt
from botragram.models.ticker import Ticker
from botragram.models.trade import Trade
from botragram.models.trading import TradingDecision, TradingResult

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "Account",
    "Balance",
    "BacktestMetrics",
    "BacktestRequest",
    "BacktestResult",
    "BacktestTrade",
    "Candle",
    "ExecutionAuthorization",
    "ExecutionAuthorizationOutcome",
    "Notification",
    "Order",
    "Position",
    "PositionSize",
    "RiskMetrics",
    "RiskResult",
    "Signal",
    "SubmissionAttempt",
    "Ticker",
    "Trade",
    "TradingDecision",
    "TradingResult",
]
