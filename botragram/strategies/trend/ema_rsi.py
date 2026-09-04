"""
Botragram

Description:
    EMA trend strategy with RSI confirmation.

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
from botragram.indicators import calculate_ema, calculate_rsi
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "EMARsiStrategy",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE = Decimal("1")
_DECIMAL_ONE_HUNDRED = Decimal("100")
_BASE_CONFIDENCE = Decimal("0.60")
_MAX_CONFIDENCE = Decimal("0.95")
_RSI_WEIGHT = Decimal("0.20")
_SEPARATION_SCALE = Decimal("0.005")
_SEPARATION_WEIGHT = Decimal("0.15")


# =============================================================================
# Strategy Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class EMARsiStrategy(BaseStrategy):
    """Generate signals from EMA trend and RSI confirmation."""

    fast_period: int = 9
    slow_period: int = 21

    rsi_period: int = 14
    rsi_overbought: Decimal = Decimal("70")
    rsi_oversold: Decimal = Decimal("30")

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if self.fast_period <= 0:
            raise ValueError("EMA fast period must be greater than zero")

        if self.slow_period <= 0:
            raise ValueError("EMA slow period must be greater than zero")

        if self.fast_period >= self.slow_period:
            raise ValueError("EMA fast period must be less than slow period")

        if self.rsi_period <= 0:
            raise ValueError("RSI period must be greater than zero")

        if not (
            _DECIMAL_ZERO
            <= self.rsi_oversold
            < self.rsi_overbought
            <= _DECIMAL_ONE_HUNDRED
        ):
            raise ValueError(
                "RSI thresholds must satisfy 0 <= oversold < overbought <= 100"
            )

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.EMA_RSI

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        return max(
            self.slow_period,
            self.rsi_period + 1,
        )

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a signal from EMA trend and RSI confirmation."""
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
        rsi_values = calculate_rsi(
            close_prices,
            period=self.rsi_period,
        )

        latest_fast_ema = fast_ema[-1]
        latest_slow_ema = slow_ema[-1]
        latest_rsi = rsi_values[-1]

        signal_type, reason = self._resolve_signal(
            fast_ema=latest_fast_ema,
            slow_ema=latest_slow_ema,
            rsi=latest_rsi,
        )

        latest_candle = candles[-1]

        return Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=latest_candle.close_price,
            confidence=self._calculate_confidence(
                signal_type=signal_type,
                fast_ema=latest_fast_ema,
                slow_ema=latest_slow_ema,
                rsi=latest_rsi,
            ),
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            reason=reason,
        )

    def _resolve_signal(
        self,
        *,
        fast_ema: Decimal,
        slow_ema: Decimal,
        rsi: Decimal,
    ) -> tuple[SignalType, str]:
        """Resolve the EMA and RSI signal."""
        if fast_ema > slow_ema and rsi <= self.rsi_oversold:
            return (
                SignalType.BUY,
                "Fast EMA is above slow EMA and RSI is oversold",
            )

        if fast_ema < slow_ema and rsi >= self.rsi_overbought:
            return (
                SignalType.SELL,
                "Fast EMA is below slow EMA and RSI is overbought",
            )

        return (
            SignalType.HOLD,
            "EMA trend and RSI confirmation are not aligned",
        )

    def _calculate_confidence(
        self,
        *,
        signal_type: SignalType,
        fast_ema: Decimal,
        slow_ema: Decimal,
        rsi: Decimal,
    ) -> Decimal:
        """Calculate normalized signal confidence."""
        if signal_type is SignalType.HOLD:
            return _DECIMAL_ZERO

        trend_ratio = self._calculate_trend_confidence(
            fast_ema=fast_ema,
            slow_ema=slow_ema,
        )
        rsi_confidence = self._calculate_rsi_confidence(
            signal_type=signal_type,
            rsi=rsi,
        )

        trend_bonus = trend_ratio * _SEPARATION_WEIGHT
        rsi_bonus = rsi_confidence * _RSI_WEIGHT

        return min(
            _BASE_CONFIDENCE + trend_bonus + rsi_bonus,
            _MAX_CONFIDENCE,
        )

    @staticmethod
    def _calculate_trend_confidence(
        *,
        fast_ema: Decimal,
        slow_ema: Decimal,
    ) -> Decimal:
        """Calculate normalized EMA separation."""
        if slow_ema == _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        return min(
            abs(fast_ema - slow_ema) / abs(slow_ema) / _SEPARATION_SCALE,
            _DECIMAL_ONE,
        )

    def _calculate_rsi_confidence(
        self,
        *,
        signal_type: SignalType,
        rsi: Decimal,
    ) -> Decimal:
        """Calculate normalized RSI threshold distance."""
        if signal_type is SignalType.BUY:
            if self.rsi_oversold == _DECIMAL_ZERO:
                return _DECIMAL_ONE

            return min(
                (self.rsi_oversold - rsi) / self.rsi_oversold
                if rsi < self.rsi_oversold
                else _DECIMAL_ZERO,
                _DECIMAL_ONE,
            )

        distance_to_maximum = _DECIMAL_ONE_HUNDRED - self.rsi_overbought

        if distance_to_maximum == _DECIMAL_ZERO:
            return _DECIMAL_ONE

        return min(
            (rsi - self.rsi_overbought) / distance_to_maximum
            if rsi > self.rsi_overbought
            else _DECIMAL_ZERO,
            _DECIMAL_ONE,
        )
