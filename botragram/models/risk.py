"""
Botragram

Description:
    Risk management domain models.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from dataclasses import dataclass
from decimal import Decimal

__all__ = [
    "PositionSize",
    "RiskMetrics",
    "RiskResult",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class PositionSize:
    """Calculated position sizing."""

    quantity: Decimal

    notional: Decimal

    leverage: int


@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class RiskMetrics:
    """Risk and reward calculation."""

    entry_price: Decimal

    stop_loss: Decimal

    take_profit: Decimal

    risk_amount: Decimal

    reward_amount: Decimal

    risk_reward_ratio: Decimal


@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class RiskResult:
    """Risk evaluation result."""

    approved: bool

    position: PositionSize

    metrics: RiskMetrics

    reason: str = ""