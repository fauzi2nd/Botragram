"""Immutable authoritative LIVE entry risk-evaluation result."""

from __future__ import annotations

from dataclasses import dataclass

from botragram.models.trading import TradingDecision

__all__ = ["LiveEntryRiskEvaluation"]


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveEntryRiskEvaluation:
    """Describe one current portfolio-aware LIVE entry decision."""

    decision: TradingDecision
    has_existing_position: bool
