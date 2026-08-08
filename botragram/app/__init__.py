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
from botragram.app.backtest_command import (
    format_backtest_report,
    is_backtest_command,
    parse_backtest_request,
    run_backtest_command,
)
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
from botragram.app.trading_runner import TradingCycleExecutor, TradingRunner

__all__ = [
    "Application",
    "ApplicationLifecycle",
    "DependencyProvider",
    "MarketStreamTelemetry",
    "MarketTypeSwitchService",
    "RuntimeRestartCoordinator",
    "SettingsManager",
    "TerminalMonitor",
    "TerminalStatus",
    "TradingCycleExecutor",
    "TradingRunner",
    "TradingRuntimeControl",
    "format_backtest_report",
    "is_backtest_command",
    "parse_backtest_request",
    "run_until_restart",
    "run_backtest_command",
    "shutdown_application",
    "startup_application",
]
