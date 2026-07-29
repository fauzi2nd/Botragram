"""
Botragram

Description:
    Signal engine for evaluating market data against strategy rules.

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
import logging

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.signal_type import SignalType
from botragram.exchanges.base.mapper import Candle
from botragram.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


# =============================================================================
# Signal Engine Class
# =============================================================================
class SignalEngine:
    """Engine responsible for evaluating market candles to produce trading signals."""

    def __init__(self, strategy: BaseStrategy) -> None:
        """Initialize SignalEngine with a trading strategy.

        Args:
            strategy: Concrete BaseStrategy implementation.
        """
        self._strategy = strategy

    @property
    def strategy(self) -> BaseStrategy:
        """Get current active strategy.

        Returns:
            BaseStrategy instance.
        """
        return self._strategy

    def set_strategy(self, strategy: BaseStrategy) -> None:
        """Update active strategy instance.

        Args:
            strategy: New BaseStrategy instance.
        """
        self._strategy = strategy
        logger.info(f"SignalEngine strategy updated to: {strategy.name}")

    def evaluate(self, candles: list[Candle]) -> SignalType:
        """Evaluate candles and generate signal.

        Args:
            candles: Historical candlestick list.

        Returns:
            SignalType enum output.
        """
        signal = self._strategy.generate_signal(candles)
        if signal != SignalType.NEUTRAL:
            logger.info(
                f"SignalEngine generated signal [{signal.value}] using {self._strategy.name}"
            )
        return signal
