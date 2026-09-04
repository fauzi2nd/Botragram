"""
Botragram

Description:
    Application package initialization.

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
from botragram.app.application import Application
from botragram.app.backfill_command import (
    format_backfill_report,
    is_backfill_command,
    parse_backfill_request,
    run_backfill_command,
)
from botragram.app.dependency_provider import DependencyProvider
from botragram.app.global_discovery_telemetry import (
    GlobalDiscoveryCandidate,
    GlobalDiscoverySnapshot,
    GlobalDiscoveryTelemetry,
)
from botragram.app.lifecycle import ApplicationLifecycle
from botragram.app.market_type_switch import (
    MarketTypeSwitchService,
    RuntimeRestartCoordinator,
    prepare_restarted_runtime_session,
    run_until_restart,
)
from botragram.app.operator_terminal_monitor import TerminalMonitor
from botragram.app.runtime_control import MarketStreamTelemetry, TradingRuntimeControl
from botragram.app.runtime_instance_lock import RuntimeInstanceLock
from botragram.app.settings_manager import SettingsManager
from botragram.app.shutdown import shutdown_application
from botragram.app.startup import startup_application
from botragram.app.terminal_monitor import TerminalStatus
from botragram.app.trading_runner import (
    AutonomousLiveCycleUnsafeError,
    AutonomousLiveTradingCycleExecutor,
    AutonomousPaperTradingCycleExecutor,
    HumanConfirmedPaperTradingCycleExecutor,
    MultiContextActivationPreconditionProvider,
    MultiContextRunnerActivationPreconditions,
    SingleSymbolTradingCycleExecutor,
    TradingCycleExecutor,
    TradingRunner,
    calculate_seconds_until_next_candle_close,
)

__all__ = [
    "Application",
    "ApplicationLifecycle",
    "AutonomousLiveCycleUnsafeError",
    "AutonomousLiveTradingCycleExecutor",
    "AutonomousPaperTradingCycleExecutor",
    "DependencyProvider",
    "HumanConfirmedPaperTradingCycleExecutor",
    "MarketStreamTelemetry",
    "MarketTypeSwitchService",
    "MultiContextActivationPreconditionProvider",
    "MultiContextRunnerActivationPreconditions",
    "RuntimeInstanceLock",
    "RuntimeRestartCoordinator",
    "SettingsManager",
    "SingleSymbolTradingCycleExecutor",
    "TerminalMonitor",
    "GlobalDiscoveryCandidate",
    "GlobalDiscoverySnapshot",
    "GlobalDiscoveryTelemetry",
    "TerminalStatus",
    "TradingCycleExecutor",
    "TradingRunner",
    "TradingRuntimeControl",
    "calculate_seconds_until_next_candle_close",
    "format_backfill_report",
    "is_backfill_command",
    "parse_backfill_request",
    "prepare_restarted_runtime_session",
    "run_backfill_command",
    "run_until_restart",
    "shutdown_application",
    "startup_application",
]
