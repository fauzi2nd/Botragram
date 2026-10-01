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
from botragram.repositories.discovery.opportunity_claim_repository import (
    AutonomousLiveOpportunityClaimRepository,
)
from botragram.repositories.execution.execution_authorization_repository import (
    ExecutionAuthorizationRepository,
)
from botragram.repositories.execution.order_repository import OrderRepository
from botragram.repositories.execution.signal_repository import SignalRepository
from botragram.repositories.execution.submission_attempt_repository import (
    SubmissionAttemptRepository,
)
from botragram.repositories.execution.trade_repository import TradeRepository
from botragram.repositories.market.candle_repository import CandleRepository
from botragram.repositories.position.closed_position_lifecycle_repository import (
    ClosedPositionLifecycleRepository,
)
from botragram.repositories.position.operator_exit_repository import (
    OperatorExitRepository,
)
from botragram.repositories.position.position_repository import PositionRepository
from botragram.repositories.runtime.live_equity_high_water_repository import (
    LiveEquityHighWaterRepository,
)
from botragram.repositories.runtime.runtime_risk_limit_repository import (
    RuntimeRiskLimitRepository,
)
from botragram.repositories.runtime.runtime_settings_repository import (
    RuntimeSettingsRepository,
)

__all__ = [
    "ClosedPositionLifecycleRepository",
    "AutonomousLiveOpportunityClaimRepository",
    "CandleRepository",
    "ExecutionAuthorizationRepository",
    "SignalRepository",
    "OrderRepository",
    "OperatorExitRepository",
    "LiveEquityHighWaterRepository",
    "TradeRepository",
    "PositionRepository",
    "SubmissionAttemptRepository",
    "RuntimeRiskLimitRepository",
    "RuntimeSettingsRepository",
]
