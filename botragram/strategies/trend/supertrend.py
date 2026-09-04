"""
Botragram

Description:
    Supertrend trend-following strategy.

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
from botragram.indicators import calculate_supertrend
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "SupertrendStrategy",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE = Decimal("1")
_BASE_CONFIDENCE = Decimal("0.60")
_MAX_CONFIDENCE = Decimal("0.95")
_DISTANCE_SCALE = Decimal("0.01")
_BONUS_WEIGHT = Decimal("0.35")


# =============================================================================
# Strategy Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class SupertrendStrategy(BaseStrategy):
    """Generate signals from Supertrend direction changes."""

    period: int = 10
    multiplier: Decimal = Decimal("3")

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if self.period <= 0:
            raise ValueError("Supertrend period must be greater than zero")

        if self.multiplier <= _DECIMAL_ZERO:
            raise ValueError("Supertrend multiplier must be greater than zero")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.SUPERTREND

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        return self.period + 1

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a signal from the latest Supertrend reversal.

        Args:
            candles: Candles ordered from oldest to newest.

        Returns:
            Buy, sell, or hold signal.
        """
        self.validate_candles(
            candles=candles,
        )

        highs = tuple(candle.high_price for candle in candles)
        lows = tuple(candle.low_price for candle in candles)
        closes = tuple(candle.close_price for candle in candles)

        result = calculate_supertrend(
            highs,
            lows,
            closes,
            period=self.period,
            multiplier=self.multiplier,
        )

        previous_uptrend = result.is_uptrend[-2]
        current_uptrend = result.is_uptrend[-1]
        current_supertrend = result.values[-1]

        signal_type, reason = self._resolve_signal(
            previous_uptrend=previous_uptrend,
            current_uptrend=current_uptrend,
        )

        latest_candle = candles[-1]

        return Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=latest_candle.close_price,
            confidence=self._calculate_confidence(
                close_price=latest_candle.close_price,
                supertrend=current_supertrend,
                signal_type=signal_type,
            ),
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            reason=reason,
        )

    @staticmethod
    def _resolve_signal(
        *,
        previous_uptrend: bool,
        current_uptrend: bool,
    ) -> tuple[SignalType, str]:
        """Resolve a signal from a trend-direction change."""
        if not previous_uptrend and current_uptrend:
            return (
                SignalType.BUY,
                "Supertrend changed from downtrend to uptrend",
            )

        if previous_uptrend and not current_uptrend:
            return (
                SignalType.SELL,
                "Supertrend changed from uptrend to downtrend",
            )

        return (
            SignalType.HOLD,
            "No Supertrend direction change detected",
        )

    @staticmethod
    def _calculate_confidence(
        *,
        close_price: Decimal,
        supertrend: Decimal,
        signal_type: SignalType,
    ) -> Decimal:
        """Calculate normalized price distance from Supertrend."""
        if signal_type is SignalType.HOLD or close_price == _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        distance = abs(close_price - supertrend) / abs(close_price)
        distance_ratio = min(distance / _DISTANCE_SCALE, _DECIMAL_ONE)
        bonus = distance_ratio * _BONUS_WEIGHT

        return min(
            _BASE_CONFIDENCE + bonus,
            _MAX_CONFIDENCE,
        )
