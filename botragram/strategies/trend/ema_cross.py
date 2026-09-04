"""
Botragram

Description:
    Exponential Moving Average crossover strategy.

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
from botragram.indicators import calculate_ema
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "EMACrossStrategy",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE = Decimal("1")
_BASE_CONFIDENCE = Decimal("0.60")
_MAX_CONFIDENCE = Decimal("0.95")
_SEPARATION_SCALE = Decimal("0.005")
_BONUS_WEIGHT = Decimal("0.35")


# =============================================================================
# Strategy Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class EMACrossStrategy(BaseStrategy):
    """Generate signals from fast and slow EMA crossovers."""

    fast_period: int = 9
    slow_period: int = 21

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if self.fast_period <= 0:
            raise ValueError("EMA fast period must be greater than zero")

        if self.slow_period <= 0:
            raise ValueError("EMA slow period must be greater than zero")

        if self.fast_period >= self.slow_period:
            raise ValueError("EMA fast period must be less than slow period")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.EMA_CROSS

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        return self.slow_period + 1

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a signal from the latest EMA crossover.

        Args:
            candles: Candles ordered from oldest to newest.

        Returns:
            Buy, sell, or hold signal based on the latest crossover.
        """
        self.validate_candles(
            candles=candles,
        )

        close_prices = tuple(candle.close_price for candle in candles)

        fast_ema = calculate_ema(
            close_prices,
            period=self.fast_period,
        )
        slow_ema = calculate_ema(
            close_prices,
            period=self.slow_period,
        )

        alignment_offset = self.slow_period - self.fast_period
        aligned_fast_ema = fast_ema[alignment_offset:]

        previous_fast = aligned_fast_ema[-2]
        current_fast = aligned_fast_ema[-1]

        previous_slow = slow_ema[-2]
        current_slow = slow_ema[-1]

        signal_type, reason = self._resolve_signal(
            previous_fast=previous_fast,
            current_fast=current_fast,
            previous_slow=previous_slow,
            current_slow=current_slow,
        )

        latest_candle = candles[-1]

        return Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=latest_candle.close_price,
            confidence=self._calculate_confidence(
                signal_type=signal_type,
                fast_ema=current_fast,
                slow_ema=current_slow,
            ),
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            reason=reason,
        )

    @staticmethod
    def _resolve_signal(
        *,
        previous_fast: Decimal,
        current_fast: Decimal,
        previous_slow: Decimal,
        current_slow: Decimal,
    ) -> tuple[SignalType, str]:
        """Resolve the latest crossover signal."""
        if previous_fast <= previous_slow and current_fast > current_slow:
            return (
                SignalType.BUY,
                "Fast EMA crossed above slow EMA",
            )

        if previous_fast >= previous_slow and current_fast < current_slow:
            return (
                SignalType.SELL,
                "Fast EMA crossed below slow EMA",
            )

        return (
            SignalType.HOLD,
            "No EMA crossover detected",
        )

    @staticmethod
    def _calculate_confidence(
        *,
        signal_type: SignalType,
        fast_ema: Decimal,
        slow_ema: Decimal,
    ) -> Decimal:
        """Calculate normalized EMA separation confidence."""
        if signal_type is SignalType.HOLD or slow_ema == _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        separation = abs(fast_ema - slow_ema) / abs(slow_ema)
        separation_ratio = min(separation / _SEPARATION_SCALE, _DECIMAL_ONE)
        bonus = separation_ratio * _BONUS_WEIGHT

        return min(
            _BASE_CONFIDENCE + bonus,
            _MAX_CONFIDENCE,
        )
