"""
Botragram

Description:
    Compatibility contracts for extracted autonomous LIVE cycle execution.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.app import (
    AutonomousLiveCycleUnsafeError as AppUnsafeError,
)
from botragram.app import (
    AutonomousLiveTradingCycleExecutor as AppLiveExecutor,
)
from botragram.app.autonomous_live_cycle_executor import (
    AutonomousLiveCycleUnsafeError,
    AutonomousLiveTradingCycleExecutor,
    GlobalDiscoveryCycleReport,
)
from botragram.app.runtime.autonomous_live_cycle_executor import (
    AutonomousLiveCycleUnsafeError as RuntimeUnsafeError,
)
from botragram.app.runtime.autonomous_live_cycle_executor import (
    AutonomousLiveTradingCycleExecutor as RuntimeLiveExecutor,
)
from botragram.app.runtime.autonomous_live_cycle_executor import (
    GlobalDiscoveryCycleReport as RuntimeCycleReport,
)
from botragram.app.runtime_limited_autonomous_live_executor import (
    RuntimeLimitedAutonomousLiveTradingCycleExecutor,
)
from botragram.app.trading_runner import (
    AutonomousLiveCycleUnsafeError as RunnerUnsafeError,
)
from botragram.app.trading_runner import (
    AutonomousLiveTradingCycleExecutor as RunnerLiveExecutor,
)
from botragram.app.trading_runner import (
    GlobalDiscoveryCycleReport as RunnerCycleReport,
)

__all__: list[str] = []


def test_autonomous_live_public_imports_preserve_class_identity() -> None:
    """Existing app and runner import paths resolve to the extracted classes."""
    assert AppUnsafeError is AutonomousLiveCycleUnsafeError
    assert RunnerUnsafeError is AutonomousLiveCycleUnsafeError
    assert AppLiveExecutor is AutonomousLiveTradingCycleExecutor
    assert RunnerLiveExecutor is AutonomousLiveTradingCycleExecutor
    assert RunnerCycleReport is GlobalDiscoveryCycleReport
    assert RuntimeUnsafeError is AutonomousLiveCycleUnsafeError
    assert RuntimeLiveExecutor is AutonomousLiveTradingCycleExecutor
    assert RuntimeCycleReport is GlobalDiscoveryCycleReport
    assert issubclass(
        RuntimeLimitedAutonomousLiveTradingCycleExecutor,
        AutonomousLiveTradingCycleExecutor,
    )
