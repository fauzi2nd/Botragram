"""
Botragram

Description:
    Strategy default constants.

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

from botragram.enums import Interval, StrategyType

__all__ = [
    "DEFAULT_CONFIRMATION_CANDLES",
    "DEFAULT_COOLDOWN_CANDLES",
    "DEFAULT_MIN_SIGNAL_STRENGTH",
    "DEFAULT_MAX_SIGNAL_AGE",
    "get_strategy_default_interval",
    "get_strategy_default_exit_rates",
]

# =============================================================================
# Strategy
# =============================================================================

# Number of candles required to confirm a signal.
DEFAULT_CONFIRMATION_CANDLES: int = 1

# Number of candles to wait before opening another position.
DEFAULT_COOLDOWN_CANDLES: int = 0

# Minimum AI/strategy confidence required (0.0 - 1.0).
DEFAULT_MIN_SIGNAL_STRENGTH: Decimal = Decimal("0.70")

# Maximum age of a signal before it is discarded.
DEFAULT_MAX_SIGNAL_AGE: int = 3


def get_strategy_default_interval(strategy_type: StrategyType) -> Interval:
    """Return the natural, optimal candlestick interval for one strategy."""
    match strategy_type:
        case (
            StrategyType.EMA_SCALPING
            | StrategyType.RSI_BB_SCALPING
            | StrategyType.VWAP_BREAKOUT
        ):
            return Interval.M5
        case StrategyType.MACD_SWING:
            return Interval.H1
        case (
            StrategyType.EMA_CROSS
            | StrategyType.EMA_RSI
            | StrategyType.ICHIMOKU_CLOUD
            | StrategyType.SUPERTREND
            | StrategyType.ADX_TREND
            | StrategyType.BOLLINGER_BREAKOUT
            | _
        ):
            return Interval.M15


def get_strategy_default_exit_rates(
    strategy_type: StrategyType,
) -> tuple[Decimal, Decimal]:
    """Return the default (stop_loss_pct, take_profit_pct) for a strategy."""
    match strategy_type:
        case (
            StrategyType.EMA_SCALPING
            | StrategyType.RSI_BB_SCALPING
            | StrategyType.VWAP_BREAKOUT
        ):
            return (Decimal("0.005"), Decimal("0.01"))
        case StrategyType.MACD_SWING:
            return (Decimal("0.025"), Decimal("0.05"))
        case (
            StrategyType.EMA_CROSS
            | StrategyType.EMA_RSI
            | StrategyType.ICHIMOKU_CLOUD
            | StrategyType.SUPERTREND
            | StrategyType.ADX_TREND
            | StrategyType.BOLLINGER_BREAKOUT
            | _
        ):
            return (Decimal("0.015"), Decimal("0.03"))
