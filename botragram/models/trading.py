"""
Botragram

Description:
    Trading workflow domain models.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from dataclasses import dataclass

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models.order import Order
from botragram.models.risk import RiskResult
from botragram.models.signal import Signal

__all__ = [
    "TradingDecision",
    "TradingResult",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class TradingDecision:
    """Immutable trading execution decision."""

    should_execute: bool
    signal: Signal
    risk_result: RiskResult | None
    reason: str = ""
    requires_portfolio_reconciliation: bool = False


@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class TradingResult:
    """Immutable result of a trading service workflow."""

    executed: bool
    decision: TradingDecision
    order: Order | None
    reason: str = ""
