"""
Botragram

Description:
    Risk management default constants.

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
from decimal import Decimal

__all__ = [
    "DEFAULT_RISK_PER_TRADE",
    "DEFAULT_MAX_DAILY_LOSS",
    "DEFAULT_MAX_OPEN_POSITIONS",
    "DEFAULT_MAX_ACCOUNT_EXPOSURE",
    "DEFAULT_MIN_RISK_REWARD_RATIO",
]

# =============================================================================
# Position Risk
# =============================================================================

# Maximum account balance risked per trade (1%).
DEFAULT_RISK_PER_TRADE: Decimal = Decimal("0.01")

# =============================================================================
# Daily Risk
# =============================================================================

# Maximum daily drawdown before stopping new trades (5%).
DEFAULT_MAX_DAILY_LOSS: Decimal = Decimal("0.05")

# =============================================================================
# Portfolio Risk
# =============================================================================

# Maximum simultaneously opened positions.
DEFAULT_MAX_OPEN_POSITIONS: int = 5

# Maximum account exposure (50% of total equity).
DEFAULT_MAX_ACCOUNT_EXPOSURE: Decimal = Decimal("0.50")

# =============================================================================
# Risk / Reward
# =============================================================================

# Minimum acceptable Risk:Reward ratio.
DEFAULT_MIN_RISK_REWARD_RATIO: Decimal = Decimal("2.0")
