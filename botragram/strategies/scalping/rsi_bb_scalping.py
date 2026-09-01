"""
Botragram

Description:
    RSI and Bollinger Bands mean-reversion scalping strategy for short timeframes.

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
from botragram.indicators import calculate_bollinger_bands, calculate_rsi
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "RSIBBScalpingStrategy",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE_HUNDRED = Decimal("100")


# =============================================================================
# Strategy Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class RSIBBScalpingStrategy(BaseStrategy):
    """Generate mean-reversion scalping signals from RSI and Bollinger Bands."""

    bb_period: int = 20
    bb_standard_deviation: Decimal = Decimal("2")
    rsi_period: int = 14
    rsi_oversold: Decimal = Decimal("30")
    rsi_overbought: Decimal = Decimal("70")

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if self.bb_period <= 0:
            raise ValueError("Bollinger Bands period must be greater than zero")

        if self.bb_standard_deviation <= _DECIMAL_ZERO:
            raise ValueError("Bollinger Bands standard deviation must be positive")

        if self.rsi_period <= 0:
            raise ValueError("RSI period must be greater than zero")

        if not (
            _DECIMAL_ZERO
            <= self.rsi_oversold
            < self.rsi_overbought
            <= _DECIMAL_ONE_HUNDRED
        ):
            raise ValueError(
                "RSI oversold/overbought thresholds must be between 0 and 100"
            )

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.RSI_BB_SCALPING

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        return max(self.bb_period, self.rsi_period) + 2

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a scalping signal from oversold/overbought bands and RSI."""
        self.validate_candles(candles=candles)

        close_prices = tuple(candle.close_price for candle in candles)
        bb_result = calculate_bollinger_bands(
            close_prices,
            period=self.bb_period,
            standard_deviation=self.bb_standard_deviation,
        )
        rsi_series = calculate_rsi(
            close_prices,
            period=self.rsi_period,
        )

        current_candle = candles[-1]
        previous_candle = candles[-2]
        current_close = current_candle.close_price
        current_rsi = rsi_series[-1]
        previous_rsi = rsi_series[-2]
        current_lower_bb = bb_result.lower[-1]
        previous_lower_bb = bb_result.lower[-2]
        current_upper_bb = bb_result.upper[-1]
        previous_upper_bb = bb_result.upper[-2]

        signal_type, reason = self._resolve_signal(
            current_candle=current_candle,
            previous_candle=previous_candle,
            current_rsi=current_rsi,
            previous_rsi=previous_rsi,
            current_lower_bb=current_lower_bb,
            previous_lower_bb=previous_lower_bb,
            current_upper_bb=current_upper_bb,
            previous_upper_bb=previous_upper_bb,
        )

        confidence = self._calculate_confidence(
            signal_type=signal_type,
            current_close=current_close,
            lower_bb=current_lower_bb,
            upper_bb=current_upper_bb,
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
        previous_candle: Candle,
        current_rsi: Decimal,
        previous_rsi: Decimal,
        current_lower_bb: Decimal,
        previous_lower_bb: Decimal,
        current_upper_bb: Decimal,
        previous_upper_bb: Decimal,
    ) -> tuple[SignalType, str]:
        """Resolve scalping signal type and explanation."""
        # BUY (Long): Oversold bounce at or below lower Bollinger Band
        is_oversold_bounce = (
            (
                previous_candle.low_price <= previous_lower_bb
                or current_candle.low_price <= current_lower_bb
            )
            and (previous_rsi <= self.rsi_oversold or current_rsi <= self.rsi_oversold)
            and current_candle.close_price > current_candle.open_price
        )
        if is_oversold_bounce:
            return (
                SignalType.BUY,
                "RSI oversold bounce off lower Bollinger Band",
            )

        # SELL (Short): Overbought rejection at or above upper Bollinger Band
        is_overbought_rejection = (
            (
                previous_candle.high_price >= previous_upper_bb
                or current_candle.high_price >= current_upper_bb
            )
            and (
                previous_rsi >= self.rsi_overbought
                or current_rsi >= self.rsi_overbought
            )
            and current_candle.close_price < current_candle.open_price
        )
        if is_overbought_rejection:
            return (
                SignalType.SELL,
                "RSI overbought rejection off upper Bollinger Band",
            )

        return SignalType.HOLD, "No RSI/BB scalping setup triggered"

    @staticmethod
    def _calculate_confidence(
        *,
        signal_type: SignalType,
        current_close: Decimal,
        lower_bb: Decimal,
        upper_bb: Decimal,
    ) -> Decimal:
        """Calculate normalized confidence from Bollinger Band distance."""
        if signal_type is SignalType.HOLD or current_close <= _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        band_width = abs(upper_bb - lower_bb)
        if band_width <= _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        if signal_type is SignalType.BUY:
            distance = abs(current_close - lower_bb)
        else:
            distance = abs(upper_bb - current_close)

        confidence = distance / band_width
        return min(max(confidence, _DECIMAL_ZERO), Decimal("1"))
