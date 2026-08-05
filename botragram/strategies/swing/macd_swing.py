"""
Botragram

Description:
    MACD swing trading strategy.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import SignalType, StrategyType
from botragram.indicators import calculate_macd
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "MACDSwingStrategy",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE = Decimal("1")


# =============================================================================
# Strategy Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class MACDSwingStrategy(BaseStrategy):
    """Generate signals from MACD crossovers."""

    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.fast_period <= 0:
            raise ValueError("MACD fast period must be greater than zero")

        if self.slow_period <= 0:
            raise ValueError("MACD slow period must be greater than zero")

        if self.signal_period <= 0:
            raise ValueError("MACD signal period must be greater than zero")

        if self.fast_period >= self.slow_period:
            raise ValueError("MACD fast period must be less than slow period")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.MACD_SWING

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        return self.slow_period + self.signal_period - 1

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a MACD crossover signal."""
        self.validate_candles(
            candles=candles,
        )

        closes = tuple(candle.close_price for candle in candles)

        result = calculate_macd(
            closes,
            fast_period=self.fast_period,
            slow_period=self.slow_period,
            signal_period=self.signal_period,
        )

        previous_macd = result.macd[-2]
        current_macd = result.macd[-1]

        previous_signal = result.signal[-2]
        current_signal = result.signal[-1]

        signal_type, reason = self._resolve_signal(
            previous_macd=previous_macd,
            current_macd=current_macd,
            previous_signal=previous_signal,
            current_signal=current_signal,
        )

        latest = candles[-1]

        return Signal(
            symbol=latest.symbol,
            signal_type=signal_type,
            price=latest.close_price,
            confidence=self._calculate_confidence(
                current_macd=current_macd,
                current_signal=current_signal,
            ),
            strategy_name=self.strategy_type.value,
            generated_at=latest.close_time,
            reason=reason,
        )

    @staticmethod
    def _resolve_signal(
        *,
        previous_macd: Decimal,
        current_macd: Decimal,
        previous_signal: Decimal,
        current_signal: Decimal,
    ) -> tuple[SignalType, str]:
        """Resolve MACD crossover."""
        if previous_macd <= previous_signal and current_macd > current_signal:
            return (
                SignalType.BUY,
                "MACD crossed above signal line",
            )

        if previous_macd >= previous_signal and current_macd < current_signal:
            return (
                SignalType.SELL,
                "MACD crossed below signal line",
            )

        return (
            SignalType.HOLD,
            "No MACD crossover detected",
        )

    @staticmethod
    def _calculate_confidence(
        *,
        current_macd: Decimal,
        current_signal: Decimal,
    ) -> Decimal:
        """Calculate crossover confidence."""
        denominator = max(
            abs(current_macd),
            abs(current_signal),
            Decimal("1"),
        )

        confidence = abs(current_macd - current_signal) / denominator

        return min(
            confidence,
            _DECIMAL_ONE,
        )
