"""
Botragram

Description:
    VWAP and ATR volatility breakout scalping strategy for short timeframes.

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
from botragram.indicators import calculate_atr, calculate_vwap
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "VWAPBreakoutStrategy",
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
class VWAPBreakoutStrategy(BaseStrategy):
    """Generate breakout scalping signals from VWAP and ATR momentum."""

    atr_period: int = 14
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.2")

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if self.atr_period <= 0:
            raise ValueError("ATR period must be greater than zero")

        if self.volume_period <= 0:
            raise ValueError("Volume period must be greater than zero")

        if self.volume_multiplier <= _DECIMAL_ZERO:
            raise ValueError("Volume multiplier must be positive")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.VWAP_BREAKOUT

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        return max(self.atr_period, self.volume_period) + 2

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a breakout signal from VWAP crossing with volume."""
        self.validate_candles(candles=candles)

        high_prices = tuple(candle.high_price for candle in candles)
        low_prices = tuple(candle.low_price for candle in candles)
        close_prices = tuple(candle.close_price for candle in candles)
        volumes = tuple(candle.volume for candle in candles)

        vwap_series = calculate_vwap(
            high_prices,
            low_prices,
            close_prices,
            volumes,
        )
        atr_series = calculate_atr(
            high_prices,
            low_prices,
            close_prices,
            period=self.atr_period,
        )

        current_candle = candles[-1]
        previous_candle = candles[-2]
        current_close = current_candle.close_price
        previous_close = previous_candle.close_price
        current_vwap = vwap_series[-1]
        previous_vwap = vwap_series[-2]
        current_atr = atr_series[-1]

        # Calculate average volume
        recent_volumes = volumes[-self.volume_period - 1 : -1]
        avg_volume = sum(recent_volumes, start=_DECIMAL_ZERO) / Decimal(
            len(recent_volumes)
        )
        has_volume_surge = current_candle.volume >= (
            avg_volume * self.volume_multiplier
        )

        signal_type, reason = self._resolve_signal(
            current_candle=current_candle,
            current_close=current_close,
            previous_close=previous_close,
            current_vwap=current_vwap,
            previous_vwap=previous_vwap,
            has_volume_surge=has_volume_surge,
        )

        confidence = self._calculate_confidence(
            signal_type=signal_type,
            current_close=current_close,
            vwap=current_vwap,
            atr=current_atr,
        )

        return Signal(
            symbol=current_candle.symbol,
            signal_type=signal_type,
            price=current_close,
            confidence=confidence,
            strategy_name=self.strategy_type.value,
            generated_at=current_candle.close_time,
            reason=reason,
        )

    def _resolve_signal(
        self,
        *,
        current_candle: Candle,
        current_close: Decimal,
        previous_close: Decimal,
        current_vwap: Decimal,
        previous_vwap: Decimal,
        has_volume_surge: bool,
    ) -> tuple[SignalType, str]:
        """Resolve VWAP breakout signal type and explanation."""
        # BUY (Long): Breakout crossing above VWAP with volume confirmation
        crossed_above_vwap = (
            previous_close <= previous_vwap and current_close > current_vwap
        )
        if (
            crossed_above_vwap
            and has_volume_surge
            and current_close > current_candle.open_price
        ):
            return (
                SignalType.BUY,
                "Bullish VWAP breakout with volume surge",
            )

        # SELL (Short): Breakdown crossing below VWAP with volume confirmation
        crossed_below_vwap = (
            previous_close >= previous_vwap and current_close < current_vwap
        )
        if (
            crossed_below_vwap
            and has_volume_surge
            and current_close < current_candle.open_price
        ):
            return (
                SignalType.SELL,
                "Bearish VWAP breakdown with volume surge",
            )

        return SignalType.HOLD, "No VWAP breakout setup triggered"

    @staticmethod
    def _calculate_confidence(
        *,
        signal_type: SignalType,
        current_close: Decimal,
        vwap: Decimal,
        atr: Decimal,
    ) -> Decimal:
        """Calculate confidence based on breakout distance relative to ATR."""
        if signal_type is SignalType.HOLD or atr <= _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        distance = abs(current_close - vwap)
        confidence = distance / atr
        return min(max(confidence, _DECIMAL_ZERO), _DECIMAL_ONE)
