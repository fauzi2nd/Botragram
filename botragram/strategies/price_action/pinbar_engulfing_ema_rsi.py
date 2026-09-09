"""
Botragram

Description:
    Pinbar and Engulfing candlestick price action with EMA and RSI confluence.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import PositionSide, SignalType, StrategyType
from botragram.indicators import (
    calculate_ema,
    calculate_rsi,
    calculate_sma,
    detect_engulfing,
    detect_pinbar,
)
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "PinbarEngulfingEmaRsiStrategy",
]

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_ONE: Final[Decimal] = Decimal("1")
_DEFAULT_MIN_CONFIDENCE: Final[Decimal] = Decimal("0.65")
_MAX_CONFIDENCE: Final[Decimal] = Decimal("0.95")
_PULLBACK_PROXIMITY_PCT: Final[Decimal] = Decimal("0.006")  # 0.6% proximity to EMA21
_HIGH_VOLUME_BONUS_MULTIPLIER: Final[Decimal] = Decimal("1.30")
_STRONG_WICK_BONUS_RATIO: Final[Decimal] = Decimal("0.70")
_STRONG_ENGULFING_BONUS_RATIO: Final[Decimal] = Decimal("1.25")
_CONFIDENCE_STEP_BONUS: Final[Decimal] = Decimal("0.05")


# =============================================================================
# Strategy Class
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class PinbarEngulfingEmaRsiStrategy(BaseStrategy):
    """Generate high-confluence candlestick price action trading signals."""

    trend_period: int = 200
    pullback_period: int = 21
    rsi_period: int = 14
    rsi_long_min: Decimal = Decimal("35.0")
    rsi_long_max: Decimal = Decimal("52.0")
    rsi_short_min: Decimal = Decimal("48.0")
    rsi_short_max: Decimal = Decimal("65.0")
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.10")
    min_wick_ratio: Decimal = Decimal("0.60")
    max_opposite_wick_ratio: Decimal = Decimal("0.20")
    min_engulfing_body_ratio: Decimal = Decimal("1.05")
    min_confidence: Decimal = _DEFAULT_MIN_CONFIDENCE

    def __post_init__(self) -> None:
        """Validate invariant strategy configuration parameters."""
        if self.trend_period <= 0 or self.pullback_period <= 0:
            raise ValueError("EMA trend and pullback periods must be positive")
        if self.pullback_period >= self.trend_period:
            raise ValueError("Pullback period must be smaller than trend period")
        if self.rsi_period <= 0 or self.volume_period <= 0:
            raise ValueError("RSI and volume periods must be positive")
        if not (
            _DECIMAL_ZERO <= self.rsi_long_min < self.rsi_long_max <= Decimal("100.0")
        ):
            raise ValueError("RSI long thresholds must be bounded within [0, 100]")
        if not (
            _DECIMAL_ZERO <= self.rsi_short_min < self.rsi_short_max <= Decimal("100.0")
        ):
            raise ValueError("RSI short thresholds must be bounded within [0, 100]")
        if self.volume_multiplier <= _DECIMAL_ZERO:
            raise ValueError("Volume multiplier must be positive")
        if not (_DECIMAL_ZERO < self.min_wick_ratio <= _DECIMAL_ONE):
            raise ValueError("Minimum wick ratio must be between 0 and 1")
        if not (_DECIMAL_ZERO <= self.max_opposite_wick_ratio <= _DECIMAL_ONE):
            raise ValueError("Maximum opposite wick ratio must be between 0 and 1")
        if self.min_engulfing_body_ratio <= _DECIMAL_ZERO:
            raise ValueError("Minimum engulfing body ratio must be positive")
        if not (_DECIMAL_ZERO <= self.min_confidence <= _DECIMAL_ONE):
            raise ValueError("Minimum confidence must be between 0.0 and 1.0")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type enum identifier."""
        return StrategyType.PINBAR_ENGULFING_EMA_RSI

    @property
    def minimum_candles(self) -> int:
        """Return the minimum number of candles required for execution."""
        return max(
            self.trend_period + 2,
            self.pullback_period + 2,
            self.rsi_period + 5,
            self.volume_period + 5,
        )

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a trading signal from candlestick price action and indicators."""
        self.validate_candles(candles=candles)

        close_prices = tuple(candle.close_price for candle in candles)
        volumes = tuple(candle.volume for candle in candles)

        ema_trend = calculate_ema(close_prices, period=self.trend_period)
        ema_pullback = calculate_ema(close_prices, period=self.pullback_period)
        rsi_series = calculate_rsi(close_prices, period=self.rsi_period)
        volume_sma = calculate_sma(volumes, period=self.volume_period)

        curr_candle = candles[-1]
        prev_candle = candles[-2]

        current_close = curr_candle.close_price
        current_trend = ema_trend[-1]
        current_pullback = ema_pullback[-1]
        current_rsi = rsi_series[-1]
        current_vol_sma = volume_sma[-1]

        # Volume threshold
        volume_ok = curr_candle.volume >= (self.volume_multiplier * current_vol_sma)

        # Candlestick pattern detection
        pinbar = detect_pinbar(
            candle=curr_candle,
            min_wick_ratio=self.min_wick_ratio,
            max_opposite_wick_ratio=self.max_opposite_wick_ratio,
        )
        engulfing = detect_engulfing(
            prev_candle=prev_candle,
            curr_candle=curr_candle,
            min_body_ratio=self.min_engulfing_body_ratio,
        )

        signal_type = SignalType.HOLD
        confidence = _DECIMAL_ZERO
        reason = "No candlestick confluence pattern matched"

        # Check BUY (Long) Setup
        if current_close > current_trend:
            pullback_proximity = current_pullback * (
                _DECIMAL_ONE + _PULLBACK_PROXIMITY_PCT
            )
            near_pullback = curr_candle.low_price <= pullback_proximity
            rsi_in_zone = self.rsi_long_min <= current_rsi <= self.rsi_long_max
            candle_trigger = (pinbar.matched and pinbar.side is PositionSide.LONG) or (
                engulfing.matched and engulfing.side is PositionSide.LONG
            )

            if near_pullback and rsi_in_zone and volume_ok and candle_trigger:
                pattern_label = (
                    "Bullish Pinbar"
                    if pinbar.matched and pinbar.side is PositionSide.LONG
                    else "Bullish Engulfing"
                )
                signal_type = SignalType.BUY
                confidence = self._compute_confidence(
                    pinbar_matched=pinbar.matched and pinbar.side is PositionSide.LONG,
                    pinbar_ratio=pinbar.wick_ratio,
                    engulfing_matched=engulfing.matched
                    and engulfing.side is PositionSide.LONG,
                    engulfing_ratio=engulfing.wick_ratio,
                    volume=curr_candle.volume,
                    volume_sma=current_vol_sma,
                )
                reason = (
                    f"{pattern_label} bounce at EMA{self.pullback_period} "
                    f"in EMA{self.trend_period} uptrend (RSI={current_rsi:.1f})"
                )

        # Check SELL (Short) Setup
        elif current_close < current_trend:
            pullback_proximity = current_pullback * (
                _DECIMAL_ONE - _PULLBACK_PROXIMITY_PCT
            )
            near_pullback = curr_candle.high_price >= pullback_proximity
            rsi_in_zone = self.rsi_short_min <= current_rsi <= self.rsi_short_max
            candle_trigger = (pinbar.matched and pinbar.side is PositionSide.SHORT) or (
                engulfing.matched and engulfing.side is PositionSide.SHORT
            )

            if near_pullback and rsi_in_zone and volume_ok and candle_trigger:
                pattern_label = (
                    "Bearish Pinbar"
                    if pinbar.matched and pinbar.side is PositionSide.SHORT
                    else "Bearish Engulfing"
                )
                signal_type = SignalType.SELL
                confidence = self._compute_confidence(
                    pinbar_matched=pinbar.matched and pinbar.side is PositionSide.SHORT,
                    pinbar_ratio=pinbar.wick_ratio,
                    engulfing_matched=engulfing.matched
                    and engulfing.side is PositionSide.SHORT,
                    engulfing_ratio=engulfing.wick_ratio,
                    volume=curr_candle.volume,
                    volume_sma=current_vol_sma,
                )
                reason = (
                    f"{pattern_label} rejection at EMA{self.pullback_period} "
                    f"in EMA{self.trend_period} downtrend (RSI={current_rsi:.1f})"
                )

        return Signal(
            symbol=curr_candle.symbol,
            signal_type=signal_type,
            price=curr_candle.close_price,
            confidence=confidence,
            strategy_name=self.strategy_type.value,
            generated_at=curr_candle.close_time,
            reason=reason,
        )

    def _compute_confidence(
        self,
        *,
        pinbar_matched: bool,
        pinbar_ratio: Decimal,
        engulfing_matched: bool,
        engulfing_ratio: Decimal,
        volume: Decimal,
        volume_sma: Decimal,
    ) -> Decimal:
        """Compute composite confidence score for the detected pattern."""
        score = self.min_confidence

        if pinbar_matched and pinbar_ratio >= _STRONG_WICK_BONUS_RATIO:
            score += _CONFIDENCE_STEP_BONUS

        if engulfing_matched and engulfing_ratio >= _STRONG_ENGULFING_BONUS_RATIO:
            score += _CONFIDENCE_STEP_BONUS

        if volume_sma > _DECIMAL_ZERO and volume >= (
            _HIGH_VOLUME_BONUS_MULTIPLIER * volume_sma
        ):
            score += _CONFIDENCE_STEP_BONUS

        return min(_MAX_CONFIDENCE, score)
