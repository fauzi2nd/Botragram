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
from botragram.app.dependency_provider import DependencyProvider
from botragram.app.lifecycle import ApplicationLifecycle
from botragram.app.market_type_switch import (
    MarketTypeSwitchService,
    RuntimeRestartCoordinator,
    run_until_restart,
)
from botragram.app.runtime_control import MarketStreamTelemetry, TradingRuntimeControl
from botragram.app.settings_manager import SettingsManager
from botragram.app.shutdown import shutdown_application
from botragram.app.startup import startup_application
from botragram.app.terminal_monitor import TerminalMonitor, TerminalStatus
from botragram.app.trading_runner import (
    AutonomousPaperTradingCycleExecutor,
    HumanConfirmedPaperTradingCycleExecutor,
    SingleSymbolTradingCycleExecutor,
    TradingCycleExecutor,
    TradingRunner,
)

__all__ = [
    "Application",
    "ApplicationLifecycle",
    "AutonomousPaperTradingCycleExecutor",
    "DependencyProvider",
    "HumanConfirmedPaperTradingCycleExecutor",
    "MarketStreamTelemetry",
    "MarketTypeSwitchService",
    "RuntimeRestartCoordinator",
    "SettingsManager",
    "SingleSymbolTradingCycleExecutor",
    "TerminalMonitor",
    "TerminalStatus",
    "TradingCycleExecutor",
    "TradingRunner",
    "TradingRuntimeControl",
    "run_until_restart",
    "shutdown_application",
    "startup_application",
]
