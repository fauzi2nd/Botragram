from botragram.strategies.base import BaseStrategy
from botragram.strategies.breakout import BollingerBreakoutStrategy
from botragram.strategies.factory import StrategyFactory
from botragram.strategies.scalping import EMAScalpingStrategy
from botragram.strategies.swing import (
    MACDSwingStrategy,
)
from botragram.strategies.trend import (
    EMACrossStrategy,
    EMARsiStrategy,
    SupertrendStrategy,
)

__all__ = [
    "BaseStrategy",
    "BollingerBreakoutStrategy",
    "EMACrossStrategy",
    "EMARsiStrategy",
    "EMAScalpingStrategy",
    "MACDSwingStrategy",
    "StrategyFactory",
    "SupertrendStrategy",
]
