"""
Botragram

Description:
    Bollinger Bands breakout strategy.

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
from botragram.indicators import calculate_bollinger_bands
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "BollingerBreakoutStrategy",
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
class BollingerBreakoutStrategy(BaseStrategy):
    """Generate signals from Bollinger Bands breakouts."""

    period: int = 20
    standard_deviation: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if self.period <= 0:
            raise ValueError("Bollinger Bands period must be greater than zero")

        if self.standard_deviation <= _DECIMAL_ZERO:
            raise ValueError(
                "Bollinger Bands standard deviation must be greater than zero"
            )

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.BOLLINGER_BREAKOUT

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        return self.period + 1

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a signal from the latest Bollinger Bands breakout."""
        self.validate_candles(
            candles=candles,
        )

        close_prices = tuple(candle.close_price for candle in candles)

        result = calculate_bollinger_bands(
            close_prices,
            period=self.period,
            standard_deviation=self.standard_deviation,
        )

        previous_close = close_prices[-2]
        current_close = close_prices[-1]

        previous_upper = result.upper[-2]
        current_upper = result.upper[-1]

        previous_lower = result.lower[-2]
        current_lower = result.lower[-1]

        signal_type, reason = self._resolve_signal(
            previous_close=previous_close,
            current_close=current_close,
            previous_upper=previous_upper,
            current_upper=current_upper,
            previous_lower=previous_lower,
            current_lower=current_lower,
        )

        latest_candle = candles[-1]

        return Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=latest_candle.close_price,
            confidence=self._calculate_confidence(
                signal_type=signal_type,
                close_price=current_close,
                upper_band=current_upper,
                lower_band=current_lower,
            ),
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            reason=reason,
        )

    @staticmethod
    def _resolve_signal(
        *,
        previous_close: Decimal,
        current_close: Decimal,
        previous_upper: Decimal,
        current_upper: Decimal,
        previous_lower: Decimal,
        current_lower: Decimal,
    ) -> tuple[SignalType, str]:
        """Resolve the latest Bollinger breakout signal."""
        if previous_close <= previous_upper and current_close > current_upper:
            return (
                SignalType.BUY,
                "Price broke above the upper Bollinger Band",
            )

        if previous_close >= previous_lower and current_close < current_lower:
            return (
                SignalType.SELL,
                "Price broke below the lower Bollinger Band",
            )

        return (
            SignalType.HOLD,
            "No Bollinger Bands breakout detected",
        )

    @staticmethod
    def _calculate_confidence(
        *,
        signal_type: SignalType,
        close_price: Decimal,
        upper_band: Decimal,
        lower_band: Decimal,
    ) -> Decimal:
        """Calculate normalized breakout confidence."""
        if signal_type is SignalType.HOLD or close_price == _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        if signal_type is SignalType.BUY:
            distance = (close_price - upper_band) / abs(close_price)
        else:
            distance = (lower_band - close_price) / abs(close_price)

        distance_ratio = min(
            max(distance, _DECIMAL_ZERO) / _DISTANCE_SCALE,
            _DECIMAL_ONE,
        )
        bonus = distance_ratio * _BONUS_WEIGHT

        return min(
            _BASE_CONFIDENCE + bonus,
            _MAX_CONFIDENCE,
        )
