"""Compatibility imports for PAPER runtime cycle adapters."""

from __future__ import annotations

from botragram.app.runtime.paper_cycle_executors import (
    AutonomousPaperTradingCycleExecutor,
    HumanConfirmedPaperTradingCycleExecutor,
)

__all__ = [
    "AutonomousPaperTradingCycleExecutor",
    "HumanConfirmedPaperTradingCycleExecutor",
]
