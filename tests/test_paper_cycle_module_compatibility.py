"""
Botragram

Description:
    Compatibility contracts for extracted PAPER cycle adapters.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.app import (
    AutonomousPaperTradingCycleExecutor as AppAutonomousPaperExecutor,
)
from botragram.app import (
    HumanConfirmedPaperTradingCycleExecutor as AppHumanConfirmedExecutor,
)
from botragram.app.paper_cycle_executors import (
    AutonomousPaperTradingCycleExecutor,
    HumanConfirmedPaperTradingCycleExecutor,
)
from botragram.app.runtime.paper_cycle_executors import (
    AutonomousPaperTradingCycleExecutor as RuntimeAutonomousPaperExecutor,
)
from botragram.app.runtime.paper_cycle_executors import (
    HumanConfirmedPaperTradingCycleExecutor as RuntimeHumanConfirmedExecutor,
)
from botragram.app.trading_runner import (
    AutonomousPaperTradingCycleExecutor as RunnerAutonomousPaperExecutor,
)
from botragram.app.trading_runner import (
    HumanConfirmedPaperTradingCycleExecutor as RunnerHumanConfirmedExecutor,
)

__all__: list[str] = []


def test_paper_executor_public_imports_preserve_class_identity() -> None:
    """Existing app and runner import paths resolve to the extracted classes."""
    assert AppAutonomousPaperExecutor is AutonomousPaperTradingCycleExecutor
    assert RunnerAutonomousPaperExecutor is AutonomousPaperTradingCycleExecutor
    assert AppHumanConfirmedExecutor is HumanConfirmedPaperTradingCycleExecutor
    assert RunnerHumanConfirmedExecutor is HumanConfirmedPaperTradingCycleExecutor
    assert RuntimeAutonomousPaperExecutor is AutonomousPaperTradingCycleExecutor
    assert RuntimeHumanConfirmedExecutor is HumanConfirmedPaperTradingCycleExecutor
