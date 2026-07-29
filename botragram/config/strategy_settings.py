"""
Botragram

Description:
    Strategy parameter configuration model.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.strategy_type import StrategyType


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(slots=True)
class StrategySettings:
    """Settings controlling indicator periods and strategy behavior."""

    strategy_type: StrategyType = StrategyType.EMA_CROSS
    fast_period: int = 9
    slow_period: int = 21
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
