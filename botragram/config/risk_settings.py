"""
Botragram

Description:
    Risk management rules settings model.

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


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(slots=True)
class RiskSettings:
    """Settings controlling order sizing and risk limits."""

    max_position_size_usdt: Decimal = Decimal("1000.0")
    risk_per_trade_pct: Decimal = Decimal("0.02")
    max_drawdown_pct: Decimal = Decimal("0.10")
    stop_loss_pct: Decimal = Decimal("0.02")
    take_profit_pct: Decimal = Decimal("0.04")
    leverage: int = 1
