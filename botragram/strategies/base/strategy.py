"""
Botragram

Description:
    Base trading strategy interface.

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
from collections.abc import Sequence

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import StrategyType
from botragram.models import Candle, Signal

__all__ = [
    "BaseStrategy",
]


# =============================================================================
# Abstract Strategy Classes
# =============================================================================
class BaseStrategy(ABC):
    """Abstract interface implemented by trading strategies."""

    __slots__ = ()

    @property
    @abstractmethod
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""

    @property
    @abstractmethod
    def minimum_candles(self) -> int:
        """Return the minimum candle count required for evaluation."""

    @abstractmethod
    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a trading signal from ordered candle data.

        Args:
            candles: Candles ordered from oldest to newest.

        Returns:
            Generated trading signal.

        Raises:
            ValueError: If candle data is insufficient or invalid.
        """

    def validate_candles(
        self,
        *,
        candles: Sequence[Candle],
    ) -> None:
        """Validate candle data before strategy evaluation.

        Args:
            candles: Candles ordered from oldest to newest.

        Raises:
            ValueError: If candle data is insufficient, contains mixed
                symbols, or is not chronologically ordered.
        """
        if len(candles) < self.minimum_candles:
            raise ValueError(
                f"{self.strategy_type.value} requires at least "
                f"{self.minimum_candles} candles"
            )

        first_symbol = candles[0].symbol

        if any(candle.symbol != first_symbol for candle in candles[1:]):
            raise ValueError("Strategy candles must use the same trading symbol")

        if any(
            previous.open_time >= current.open_time
            for previous, current in zip(
                candles,
                candles[1:],
                strict=False,
            )
        ):
            raise ValueError("Strategy candles must be ordered from oldest to newest")
