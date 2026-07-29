"""
Botragram

Description:
    Abstract Base Strategy class.

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
from abc import ABC, abstractmethod

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.signal_type import SignalType
from botragram.exchanges.base.mapper import Candle


# =============================================================================
# Abstract Strategy Class
# =============================================================================
class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    def __init__(self, name: str) -> None:
        """Initialize base strategy.

        Args:
            name: Strategy name string.
        """
        self._name = name

    @property
    def name(self) -> str:
        """Strategy name property.

        Returns:
            Strategy name string.
        """
        return self._name

    @abstractmethod
    def generate_signal(self, candles: list[Candle]) -> SignalType:
        """Evaluate candlestick data and generate a trading signal.

        Args:
            candles: List of Candle instances.

        Returns:
            SignalType enum instance.
        """
