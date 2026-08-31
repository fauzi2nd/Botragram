"""
Botragram

Description:
    Ichimoku Cloud equilibrium trading strategy.

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
from botragram.indicators import calculate_ichimoku
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "IchimokuCloudStrategy",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE = Decimal("1")
_DECIMAL_TWO = Decimal("2")


# =============================================================================
# Strategy Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class IchimokuCloudStrategy(BaseStrategy):
    """Generate signals from Ichimoku TK crossovers confirmed by Kumo Cloud."""

    conversion_period: int = 9
    base_period: int = 26
    leading_span_period: int = 52

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if self.conversion_period <= 0:
            raise ValueError("Ichimoku conversion period must be greater than zero")

        if self.base_period <= 0:
            raise ValueError("Ichimoku base period must be greater than zero")

        if self.leading_span_period <= 0:
            raise ValueError("Ichimoku leading span period must be greater than zero")

        if not (self.conversion_period <= self.base_period <= self.leading_span_period):
            raise ValueError(
                "Ichimoku periods must satisfy "
                "conversion_period <= base_period <= leading_span_period"
            )

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.ICHIMOKU_CLOUD

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        return self.leading_span_period + 1

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a signal from Ichimoku Cloud analysis.

        Args:
            candles: Candles ordered from oldest to newest.

        Returns:
            Buy, sell, or hold signal with confidence metrics.
        """
        self.validate_candles(
            candles=candles,
        )

        highs = tuple(candle.high_price for candle in candles)
        lows = tuple(candle.low_price for candle in candles)
        closes = tuple(candle.close_price for candle in candles)

        result = calculate_ichimoku(
            highs,
            lows,
            closes,
            conversion_period=self.conversion_period,
            base_period=self.base_period,
            leading_span_period=self.leading_span_period,
        )

        previous_conversion = result.conversion_line[-2]
        current_conversion = result.conversion_line[-1]

        previous_base = result.base_line[-2]
        current_base = result.base_line[-1]

        current_span_a = result.leading_span_a[-1]
        current_span_b = result.leading_span_b[-1]

        latest_candle = candles[-1]
        current_close = latest_candle.close_price

        signal_type, reason = self._resolve_signal(
            previous_conversion=previous_conversion,
            current_conversion=current_conversion,
            previous_base=previous_base,
            current_base=current_base,
            current_close=current_close,
            span_a=current_span_a,
            span_b=current_span_b,
        )

        return Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=current_close,
            confidence=self._calculate_confidence(
                signal_type=signal_type,
                close_price=current_close,
                conversion_line=current_conversion,
                base_line=current_base,
                span_a=current_span_a,
                span_b=current_span_b,
            ),
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            reason=reason,
        )

    @staticmethod
    def _resolve_signal(
        *,
        previous_conversion: Decimal,
        current_conversion: Decimal,
        previous_base: Decimal,
        current_base: Decimal,
        current_close: Decimal,
        span_a: Decimal,
        span_b: Decimal,
    ) -> tuple[SignalType, str]:
        """Resolve signal from TK cross and Kumo Cloud filter."""
        bullish_tk_cross = (
            previous_conversion <= previous_base and current_conversion > current_base
        )
        bearish_tk_cross = (
            previous_conversion >= previous_base and current_conversion < current_base
        )

        kumo_top = max(span_a, span_b)
        kumo_bottom = min(span_a, span_b)

        if bullish_tk_cross:
            if current_close > kumo_top:
                return (
                    SignalType.BUY,
                    "Tenkan-sen crossed above Kijun-sen with price above Kumo Cloud",
                )
            return (
                SignalType.HOLD,
                "Bullish TK cross filtered out (price is inside or below Kumo Cloud)",
            )

        if bearish_tk_cross:
            if current_close < kumo_bottom:
                return (
                    SignalType.SELL,
                    "Tenkan-sen crossed below Kijun-sen with price below Kumo Cloud",
                )
            return (
                SignalType.HOLD,
                "Bearish TK cross filtered out (price is inside or above Kumo Cloud)",
            )

        return (
            SignalType.HOLD,
            "No Ichimoku TK crossover detected",
        )

    @staticmethod
    def _calculate_confidence(
        *,
        signal_type: SignalType,
        close_price: Decimal,
        conversion_line: Decimal,
        base_line: Decimal,
        span_a: Decimal,
        span_b: Decimal,
    ) -> Decimal:
        """Calculate normalized Ichimoku confidence."""
        if signal_type is SignalType.HOLD or close_price == _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        kumo_top = max(span_a, span_b)
        kumo_bottom = min(span_a, span_b)

        if signal_type is SignalType.BUY:
            cloud_distance = (
                (close_price - kumo_top) / abs(close_price)
                if close_price > kumo_top
                else _DECIMAL_ZERO
            )
            tk_separation = (
                abs(conversion_line - base_line) / abs(base_line)
                if base_line != _DECIMAL_ZERO
                else _DECIMAL_ZERO
            )
        else:
            cloud_distance = (
                (kumo_bottom - close_price) / abs(close_price)
                if close_price < kumo_bottom
                else _DECIMAL_ZERO
            )
            tk_separation = (
                abs(conversion_line - base_line) / abs(base_line)
                if base_line != _DECIMAL_ZERO
                else _DECIMAL_ZERO
            )

        combined = (cloud_distance + tk_separation) / _DECIMAL_TWO
        return min(max(combined, _DECIMAL_ZERO), _DECIMAL_ONE)
