"""
Botragram

Description:
    EMA scalping strategy.

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
    "EMAScalpingStrategy",
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
class EMAScalpingStrategy(BaseStrategy):
    """Generate short-term signals from EMA crossover and momentum."""

    fast_period: int = 5
    slow_period: int = 13
    minimum_body_ratio: Decimal = Decimal("0.25")

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if self.fast_period <= 0:
            raise ValueError("Scalping fast period must be greater than zero")

        if self.slow_period <= 0:
            raise ValueError("Scalping slow period must be greater than zero")

        if self.fast_period >= self.slow_period:
            raise ValueError("Scalping fast period must be less than slow period")

        if not (_DECIMAL_ZERO <= self.minimum_body_ratio <= _DECIMAL_ONE):
            raise ValueError("Minimum body ratio must be between zero and one")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.EMA_SCALPING

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        return self.slow_period + 1

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a short-term EMA scalping signal."""
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

        latest_candle = candles[-1]
        body_ratio = self._calculate_body_ratio(
            candle=latest_candle,
        )

        signal_type, reason = self._resolve_signal(
            previous_fast=previous_fast,
            current_fast=current_fast,
            previous_slow=previous_slow,
            current_slow=current_slow,
            candle=latest_candle,
            body_ratio=body_ratio,
        )

        return Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=latest_candle.close_price,
            confidence=self._calculate_confidence(
                signal_type=signal_type,
                fast_ema=current_fast,
                slow_ema=current_slow,
                body_ratio=body_ratio,
            ),
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            reason=reason,
        )

    def _resolve_signal(
        self,
        *,
        previous_fast: Decimal,
        current_fast: Decimal,
        previous_slow: Decimal,
        current_slow: Decimal,
        candle: Candle,
        body_ratio: Decimal,
    ) -> tuple[SignalType, str]:
        """Resolve a scalping signal."""
        bullish_crossover = (
            previous_fast <= previous_slow and current_fast > current_slow
        )
        bearish_crossover = (
            previous_fast >= previous_slow and current_fast < current_slow
        )

        if (
            bullish_crossover
            and candle.close_price > candle.open_price
            and body_ratio >= self.minimum_body_ratio
        ):
            return (
                SignalType.BUY,
                "Bullish EMA crossover confirmed by bullish candle",
            )

        if (
            bearish_crossover
            and candle.close_price < candle.open_price
            and body_ratio >= self.minimum_body_ratio
        ):
            return (
                SignalType.SELL,
                "Bearish EMA crossover confirmed by bearish candle",
            )

        return (
            SignalType.HOLD,
            "EMA crossover or candle confirmation is absent",
        )

    @staticmethod
    def _calculate_body_ratio(
        *,
        candle: Candle,
    ) -> Decimal:
        """Calculate candle body size relative to its total range."""
        candle_range = candle.high_price - candle.low_price

        if candle_range <= _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        body_size = abs(candle.close_price - candle.open_price)

        return min(
            body_size / candle_range,
            _DECIMAL_ONE,
        )

    @staticmethod
    def _calculate_confidence(
        *,
        signal_type: SignalType,
        fast_ema: Decimal,
        slow_ema: Decimal,
        body_ratio: Decimal,
    ) -> Decimal:
        """Calculate normalized scalping confidence."""
        if signal_type is SignalType.HOLD:
            return _DECIMAL_ZERO

        if slow_ema == _DECIMAL_ZERO:
            trend_confidence = _DECIMAL_ZERO
        else:
            trend_confidence = min(
                abs(fast_ema - slow_ema) / abs(slow_ema),
                _DECIMAL_ONE,
            )

        return min(
            (trend_confidence + body_ratio) / Decimal("2"),
            _DECIMAL_ONE,
        )
