"""
Botragram

Description:
    Compatibility exports for the trading engine context.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.engine.trading.signal_engine import (
    SignalEngine,
    StructuralTargetValidator,
    TriggerGuardsValidator,
    ZoneCandidateDetailedDetector,
    ZoneCandidateDetector,
    has_account_ratio_evaluation,
    has_funding_evaluation,
    has_oi_evaluation,
)

__all__ = [
    "SignalEngine",
    "StructuralTargetValidator",
    "TriggerGuardsValidator",
    "ZoneCandidateDetailedDetector",
    "ZoneCandidateDetector",
    "has_account_ratio_evaluation",
    "has_funding_evaluation",
    "has_oi_evaluation",
]
