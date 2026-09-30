"""
Botragram

Description:
    Verify stable service exports after subsystem package moves.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.services import (
    AutonomousLiveEntryExecutionService,
    AutonomousLiveEntryIntentService,
    CandleRetentionService,
    CandleSyncService,
    ClosedPositionLifecycleService,
    ExecutionAuthorizationService,
    LiveFuturesEntryService,
    LivePositionLifecycleCoordinator,
    LiveRuntimeHealthService,
    LiveRuntimePortfolioReconciliationService,
    MarketService,
    OrderService,
    PositionExitService,
    PositionService,
    RuntimeReporter,
    RuntimeRiskLimitService,
    StoredResampledCandleProvider,
)
from botragram.services.autonomous_live_entry_execution_service import (
    AutonomousLiveEntryExecutionService as LegacyAutonomousLiveEntryExecutionService,
)
from botragram.services.autonomous_live_entry_intent_service import (
    AutonomousLiveEntryIntentService as LegacyAutonomousLiveEntryIntentService,
)
from botragram.services.candle_retention_service import (
    CandleRetentionService as LegacyCandleRetentionService,
)
from botragram.services.candle_sync_service import (
    CandleSyncService as LegacyCandleSyncService,
)
from botragram.services.closed_position_lifecycle_service import (
    ClosedPositionLifecycleService as LegacyClosedPositionLifecycleService,
)
from botragram.services.execution import (
    AutonomousLiveEntryExecutionService as ExecutionAutonomousLiveEntryExecutionService,
)
from botragram.services.execution import (
    AutonomousLiveEntryIntentService as ExecutionAutonomousLiveEntryIntentService,
)
from botragram.services.execution import (
    ExecutionAuthorizationService as ExecutionPackageAuthorizationService,
)
from botragram.services.execution import (
    LiveFuturesEntryService as ExecutionLiveFuturesEntryService,
)
from botragram.services.execution import OrderService as ExecutionOrderService
from botragram.services.execution_authorization_service import (
    ExecutionAuthorizationService as LegacyExecutionAuthorizationService,
)
from botragram.services.live_futures_entry_service import (
    LiveFuturesEntryService as LegacyLiveFuturesEntryService,
)
from botragram.services.live_position_lifecycle_coordinator import (
    LivePositionLifecycleCoordinator as LegacyLivePositionLifecycleCoordinator,
)
from botragram.services.live_runtime_health_service import (
    LiveRuntimeHealthService as LegacyLiveRuntimeHealthService,
)
from botragram.services.live_runtime_portfolio_reconciliation_service import (
    LiveRuntimePortfolioReconciliationService as LegacyPortfolioReconciliation,
)
from botragram.services.market import (
    CandleRetentionService as MarketCandleRetentionService,
)
from botragram.services.market import (
    CandleSyncService as MarketCandleSyncService,
)
from botragram.services.market import MarketService as MarketPackageService
from botragram.services.market import (
    StoredResampledCandleProvider as MarketStoredResampledCandleProvider,
)
from botragram.services.market_service import MarketService as LegacyMarketService
from botragram.services.order_service import OrderService as LegacyOrderService
from botragram.services.position import (
    ClosedPositionLifecycleService as PositionClosedPositionLifecycleService,
)
from botragram.services.position import (
    LivePositionLifecycleCoordinator as PositionLivePositionLifecycleCoordinator,
)
from botragram.services.position import (
    PositionExitService as PositionPackageExitService,
)
from botragram.services.position import PositionService as PositionPackageService
from botragram.services.position_exit_service import (
    PositionExitService as LegacyPositionExitService,
)
from botragram.services.position_service import PositionService as LegacyPositionService
from botragram.services.runtime import (
    LiveRuntimeHealthService as RuntimePackageHealthService,
)
from botragram.services.runtime import (
    LiveRuntimePortfolioReconciliationService as RuntimePortfolioReconciliation,
)
from botragram.services.runtime import RuntimeReporter as RuntimePackageReporter
from botragram.services.runtime import (
    RuntimeRiskLimitService as RuntimePackageRiskLimitService,
)
from botragram.services.runtime_reporter import RuntimeReporter as LegacyRuntimeReporter
from botragram.services.runtime_risk_limit_service import (
    RuntimeRiskLimitService as LegacyRuntimeRiskLimitService,
)
from botragram.services.stored_resampled_candle_provider import (
    StoredResampledCandleProvider as LegacyStoredResampledCandleProvider,
)


def test_market_service_exports_preserve_class_identity() -> None:
    """Keep established service imports bound to the relocated classes."""
    assert CandleRetentionService is MarketCandleRetentionService
    assert CandleRetentionService is LegacyCandleRetentionService
    assert CandleSyncService is MarketCandleSyncService
    assert CandleSyncService is LegacyCandleSyncService
    assert MarketService is MarketPackageService
    assert MarketService is LegacyMarketService
    assert StoredResampledCandleProvider is MarketStoredResampledCandleProvider
    assert StoredResampledCandleProvider is LegacyStoredResampledCandleProvider


def test_position_service_exports_preserve_class_identity() -> None:
    """Keep established position imports bound to the relocated classes."""
    assert ClosedPositionLifecycleService is PositionClosedPositionLifecycleService
    assert ClosedPositionLifecycleService is LegacyClosedPositionLifecycleService
    assert LivePositionLifecycleCoordinator is PositionLivePositionLifecycleCoordinator
    assert LivePositionLifecycleCoordinator is LegacyLivePositionLifecycleCoordinator
    assert PositionExitService is PositionPackageExitService
    assert PositionExitService is LegacyPositionExitService
    assert PositionService is PositionPackageService
    assert PositionService is LegacyPositionService


def test_execution_service_exports_preserve_class_identity() -> None:
    """Keep existing authorization and order imports bound to one class each."""
    assert (
        AutonomousLiveEntryExecutionService
        is ExecutionAutonomousLiveEntryExecutionService
        is LegacyAutonomousLiveEntryExecutionService
    )
    assert (
        AutonomousLiveEntryIntentService
        is ExecutionAutonomousLiveEntryIntentService
        is LegacyAutonomousLiveEntryIntentService
    )
    assert (
        ExecutionAuthorizationService
        is ExecutionPackageAuthorizationService
        is LegacyExecutionAuthorizationService
    )
    assert (
        LiveFuturesEntryService
        is ExecutionLiveFuturesEntryService
        is LegacyLiveFuturesEntryService
    )
    assert OrderService is ExecutionOrderService is LegacyOrderService


def test_runtime_service_exports_preserve_class_identity() -> None:
    """Keep existing health, reconciliation, and reporting imports stable."""
    assert (
        LiveRuntimeHealthService
        is RuntimePackageHealthService
        is LegacyLiveRuntimeHealthService
    )
    assert (
        LiveRuntimePortfolioReconciliationService
        is RuntimePortfolioReconciliation
        is LegacyPortfolioReconciliation
    )
    assert RuntimeReporter is RuntimePackageReporter is LegacyRuntimeReporter
    assert (
        RuntimeRiskLimitService
        is RuntimePackageRiskLimitService
        is LegacyRuntimeRiskLimitService
    )
