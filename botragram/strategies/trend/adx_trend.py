"""
Botragram

Description:
    ADX trend-following strategy with EMA and directional movement confirmation.

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
from botragram.indicators import calculate_adx, calculate_ema
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "ADXTrendStrategy",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE = Decimal("1")
_DECIMAL_TWO = Decimal("2")
_DECIMAL_ONE_HUNDRED = Decimal("100")


# =============================================================================
# Strategy Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class ADXTrendStrategy(BaseStrategy):
    """Generate signals from EMA trend confirmed by ADX trend strength."""

    adx_period: int = 14
    fast_period: int = 9
    slow_period: int = 21
    adx_threshold: Decimal = Decimal("25.0")

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if self.adx_period <= 0:
            raise ValueError("ADX period must be greater than zero")

        if self.fast_period <= 0:
            raise ValueError("EMA fast period must be greater than zero")

        if self.slow_period <= 0:
            raise ValueError("EMA slow period must be greater than zero")

        if self.fast_period >= self.slow_period:
            raise ValueError("EMA fast period must be less than slow period")

        if not (_DECIMAL_ZERO <= self.adx_threshold <= _DECIMAL_ONE_HUNDRED):
            raise ValueError("ADX threshold must be between 0 and 100")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.ADX_TREND

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        return max(
            (self.adx_period * 2),
            self.slow_period + 1,
        )

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a signal from ADX strength and EMA alignment.

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

        adx_result = calculate_adx(
            highs,
            lows,
            closes,
            period=self.adx_period,
        )

        fast_ema = calculate_ema(
            closes,
            period=self.fast_period,
        )
        slow_ema = calculate_ema(
            closes,
            period=self.slow_period,
        )

        latest_adx = adx_result.adx[-1]
        latest_plus_di = adx_result.plus_di[-1]
        latest_minus_di = adx_result.minus_di[-1]
        latest_fast = fast_ema[-1]
        latest_slow = slow_ema[-1]

        signal_type, reason = self._resolve_signal(
            adx=latest_adx,
            plus_di=latest_plus_di,
            minus_di=latest_minus_di,
            fast_ema=latest_fast,
            slow_ema=latest_slow,
        )

        latest_candle = candles[-1]

        return Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=latest_candle.close_price,
            confidence=self._calculate_confidence(
                signal_type=signal_type,
                adx=latest_adx,
                plus_di=latest_plus_di,
                minus_di=latest_minus_di,
                fast_ema=latest_fast,
                slow_ema=latest_slow,
            ),
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            reason=reason,
        )

    def _resolve_signal(
        self,
        *,
        adx: Decimal,
        plus_di: Decimal,
        minus_di: Decimal,
        fast_ema: Decimal,
        slow_ema: Decimal,
    ) -> tuple[SignalType, str]:
        """Resolve signal based on ADX strength, +DI/-DI, and EMA trend."""
        if adx < self.adx_threshold:
            return (
                SignalType.HOLD,
                f"ADX ({adx:.1f}) is below trend threshold ({self.adx_threshold:.1f})",
            )

        bullish_trend = fast_ema > slow_ema and plus_di > minus_di
        bearish_trend = fast_ema < slow_ema and minus_di > plus_di

        if bullish_trend:
            return (
                SignalType.BUY,
                "Bullish EMA trend and +DI > -DI confirmed by strong ADX",
            )

        if bearish_trend:
            return (
                SignalType.SELL,
                "Bearish EMA trend and -DI > +DI confirmed by strong ADX",
            )

        return (
            SignalType.HOLD,
            "EMA trend and directional indicators are not aligned",
        )

    def _calculate_confidence(
        self,
        *,
        signal_type: SignalType,
        adx: Decimal,
        plus_di: Decimal,
        minus_di: Decimal,
        fast_ema: Decimal,
        slow_ema: Decimal,
    ) -> Decimal:
        """Calculate normalized ADX and trend confidence."""
        if signal_type is SignalType.HOLD:
            return _DECIMAL_ZERO

        max_adx_span = _DECIMAL_ONE_HUNDRED - self.adx_threshold
        if max_adx_span <= _DECIMAL_ZERO:
            adx_confidence = _DECIMAL_ONE
        else:
            adx_confidence = min(
                max((adx - self.adx_threshold) / max_adx_span, _DECIMAL_ZERO),
                _DECIMAL_ONE,
            )

        di_sum = plus_di + minus_di
        di_confidence = (
            abs(plus_di - minus_di) / di_sum
            if di_sum > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )

        trend_confidence = (
            abs(fast_ema - slow_ema) / abs(slow_ema)
            if slow_ema != _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )

        combined = (adx_confidence + di_confidence + trend_confidence) / Decimal("3")
        return min(max(combined, _DECIMAL_ZERO), _DECIMAL_ONE)
