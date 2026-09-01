"""
Botragram

Description:
    Scalping strategies package initialization.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.strategies.scalping.ema_scalping import (
    EMAScalpingStrategy,
)
from botragram.strategies.scalping.rsi_bb_scalping import (
    RSIBBScalpingStrategy,
)
from botragram.strategies.scalping.vwap_breakout import (
    VWAPBreakoutStrategy,
)

__all__ = [
    "EMAScalpingStrategy",
    "RSIBBScalpingStrategy",
    "VWAPBreakoutStrategy",
]
