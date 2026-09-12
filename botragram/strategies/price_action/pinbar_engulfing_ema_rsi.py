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
    calculate_atr,
    calculate_ema,
    calculate_rsi,
    calculate_sma,
    detect_engulfing,
    detect_pinbar,
)
from botragram.indicators.price_action import find_swing_levels
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
    use_open_interest: bool = False
    min_oi_change_pct: Decimal = _DECIMAL_ZERO
    oi_confidence_bonus: Decimal = _CONFIDENCE_STEP_BONUS
    require_oi_confluence: bool = False
    require_key_level_location: bool = True
    swing_lookback: int = 15
    location_tolerance_pct: Decimal = Decimal("0.030")

    # Structural SL/TP & Volatility/Trend Gates
    atr_period: int = 14
    atr_multiplier_sl: Decimal = Decimal("0.5")
    risk_reward_ratio: Decimal = Decimal("2.0")
    require_trend_filter: bool = True
    min_natr_threshold: Decimal = Decimal("0.0020")
    min_sl_distance_pct: Decimal = Decimal("0.0080")

    # Account Long-Short Ratio Sentiment Filter
    filter_account_ratio: bool = False
    max_long_account_ratio: Decimal = Decimal("0.75")
    min_short_account_ratio: Decimal = Decimal("0.25")
    require_account_ratio_confluence: bool = False
    confirm_htf_account_ratio: bool = False

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
        if self.min_oi_change_pct < _DECIMAL_ZERO:
            raise ValueError("Minimum OI change percentage must be non-negative")
        if self.oi_confidence_bonus < _DECIMAL_ZERO:
            raise ValueError("OI confidence bonus must be non-negative")
        if self.swing_lookback <= 2:
            raise ValueError("Swing lookback must be greater than 2")
        if self.location_tolerance_pct < _DECIMAL_ZERO:
            raise ValueError("Location tolerance percentage must not be negative")
        if self.atr_period <= 2 or self.atr_multiplier_sl <= _DECIMAL_ZERO:
            raise ValueError("ATR parameters must be positive")
        if self.risk_reward_ratio <= _DECIMAL_ZERO:
            raise ValueError("Risk reward ratio must be positive")
        if self.min_natr_threshold < _DECIMAL_ZERO:
            raise ValueError("Minimum NATR threshold must not be negative")
        if self.min_sl_distance_pct < _DECIMAL_ZERO:
            raise ValueError("Minimum SL distance pct must be non-negative")

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
            self.atr_period + 5,
            (self.swing_lookback * 2 + 1) if self.require_key_level_location else 1,
        )

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a trading signal from candlestick price action and indicators."""
        self.validate_candles(candles=candles)

        high_prices = tuple(candle.high_price for candle in candles)
        low_prices = tuple(candle.low_price for candle in candles)
        close_prices = tuple(candle.close_price for candle in candles)
        volumes = tuple(candle.volume for candle in candles)

        ema_trend = calculate_ema(close_prices, period=self.trend_period)
        ema_pullback = calculate_ema(close_prices, period=self.pullback_period)
        rsi_series = calculate_rsi(close_prices, period=self.rsi_period)
        volume_sma = calculate_sma(volumes, period=self.volume_period)
        atr_series = calculate_atr(
            high_prices, low_prices, close_prices, period=self.atr_period
        )

        if self.require_key_level_location:
            last_swing_high, last_swing_low = find_swing_levels(
                high_prices=high_prices[:-1],
                low_prices=low_prices[:-1],
                swing_window=self.swing_lookback,
            )
        else:
            last_swing_high, last_swing_low = None, None

        curr_candle = candles[-1]
        prev_candle = candles[-2]

        current_close = curr_candle.close_price
        current_trend = ema_trend[-1]
        current_pullback = ema_pullback[-1]
        current_rsi = rsi_series[-1]
        current_vol_sma = volume_sma[-1]
        current_atr = atr_series[-1]

        # Check NATR Dead Market Volatility Gate
        if (
            current_close > _DECIMAL_ZERO
            and (current_atr / current_close) < self.min_natr_threshold
        ):
            return Signal(
                symbol=curr_candle.symbol,
                signal_type=SignalType.HOLD,
                price=curr_candle.close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=curr_candle.close_time,
                reason=(
                    "Dead market volatility rejected (NATR="
                    f"{current_atr / current_close:.4f} < "
                    f"{self.min_natr_threshold:.4f})"
                ),
            )

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

        # Check BUY (Long) Setup with Dual EMA Alignment
        uptrend_aligned = current_close > current_trend and (
            not self.require_trend_filter or current_pullback >= current_trend
        )
        if uptrend_aligned:
            pullback_proximity = current_pullback * (
                _DECIMAL_ONE + _PULLBACK_PROXIMITY_PCT
            )
            near_pullback = curr_candle.low_price <= pullback_proximity
            rsi_in_zone = self.rsi_long_min <= current_rsi <= self.rsi_long_max
            candle_trigger = (pinbar.matched and pinbar.side is PositionSide.LONG) or (
                engulfing.matched and engulfing.side is PositionSide.LONG
            )

            # Key level location check: Dynamic EMA Support or Swing Low Support
            tolerance = current_pullback * self.location_tolerance_pct
            at_ema_support = (
                (curr_candle.low_price - tolerance)
                <= current_pullback
                <= (curr_candle.high_price + tolerance)
            )
            at_swing_support = last_swing_low is not None and (
                (curr_candle.low_price - tolerance)
                <= last_swing_low
                <= (curr_candle.high_price + tolerance)
            )
            location_ok = (
                not self.require_key_level_location
                or at_ema_support
                or at_swing_support
            )

            if (
                near_pullback
                and rsi_in_zone
                and volume_ok
                and candle_trigger
                and location_ok
            ):
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
                pattern_low = min(curr_candle.low_price, prev_candle.low_price)
                stop_loss = pattern_low - (self.atr_multiplier_sl * current_atr)
                risk_dist = current_close - stop_loss
                if risk_dist <= _DECIMAL_ZERO:
                    stop_loss = current_close - (self.atr_multiplier_sl * current_atr)
                    risk_dist = self.atr_multiplier_sl * current_atr

                min_risk_dist = current_close * self.min_sl_distance_pct
                if risk_dist < min_risk_dist:
                    risk_dist = min_risk_dist
                    stop_loss = current_close - risk_dist

                take_profit = current_close + (risk_dist * self.risk_reward_ratio)

                reason = (
                    f"{pattern_label} bounce at key location "
                    f"(EMA{self.pullback_period} or Swing Low) "
                    f"in EMA{self.trend_period} uptrend "
                    f"(RSI={current_rsi:.1f}) | "
                    f"SL: {stop_loss:.5f} | TP: {take_profit:.5f}"
                )

        # Check SELL (Short) Setup with Dual EMA Alignment
        downtrend_aligned = current_close < current_trend and (
            not self.require_trend_filter or current_pullback <= current_trend
        )
        if signal_type is SignalType.HOLD and downtrend_aligned:
            pullback_proximity = current_pullback * (
                _DECIMAL_ONE - _PULLBACK_PROXIMITY_PCT
            )
            near_pullback = curr_candle.high_price >= pullback_proximity
            rsi_in_zone = self.rsi_short_min <= current_rsi <= self.rsi_short_max
            candle_trigger = (pinbar.matched and pinbar.side is PositionSide.SHORT) or (
                engulfing.matched and engulfing.side is PositionSide.SHORT
            )

            # Key level location check: Dynamic EMA Resistance or Swing High Resistance
            tolerance = current_pullback * self.location_tolerance_pct
            at_ema_resistance = (
                (curr_candle.low_price - tolerance)
                <= current_pullback
                <= (curr_candle.high_price + tolerance)
            )
            at_swing_resistance = last_swing_high is not None and (
                (curr_candle.low_price - tolerance)
                <= last_swing_high
                <= (curr_candle.high_price + tolerance)
            )
            location_ok = (
                not self.require_key_level_location
                or at_ema_resistance
                or at_swing_resistance
            )

            if (
                near_pullback
                and rsi_in_zone
                and volume_ok
                and candle_trigger
                and location_ok
            ):
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
                pattern_high = max(curr_candle.high_price, prev_candle.high_price)
                stop_loss = pattern_high + (self.atr_multiplier_sl * current_atr)
                risk_dist = stop_loss - current_close
                if risk_dist <= _DECIMAL_ZERO:
                    stop_loss = current_close - (self.atr_multiplier_sl * current_atr)
                    risk_dist = self.atr_multiplier_sl * current_atr

                min_risk_dist = current_close * self.min_sl_distance_pct
                if risk_dist < min_risk_dist:
                    risk_dist = min_risk_dist
                    stop_loss = current_close + risk_dist

                take_profit = current_close - (risk_dist * self.risk_reward_ratio)

                reason = (
                    f"{pattern_label} rejection at key location "
                    f"(EMA{self.pullback_period} or Swing High) "
                    f"in EMA{self.trend_period} downtrend "
                    f"(RSI={current_rsi:.1f}) | "
                    f"SL: {stop_loss:.5f} | TP: {take_profit:.5f}"
                )

        signal = Signal(
            symbol=curr_candle.symbol,
            signal_type=signal_type,
            price=curr_candle.close_price,
            confidence=confidence,
            strategy_name=self.strategy_type.value,
            generated_at=curr_candle.close_time,
            reason=reason,
        )

        if self.use_open_interest and signal_type is not SignalType.HOLD:
            signal = self.apply_open_interest_confluence(
                signal=signal,
                candles=candles,
                min_change_pct=self.min_oi_change_pct,
                confidence_bonus=self.oi_confidence_bonus,
                strict=self.require_oi_confluence,
            )

        if self.filter_account_ratio and signal.signal_type is not SignalType.HOLD:
            signal = self.apply_account_ratio_filter(
                signal=signal,
                candles=candles,
                max_long_ratio=self.max_long_account_ratio,
                min_short_ratio=self.min_short_account_ratio,
                strict=self.require_account_ratio_confluence,
                confirm_htf=self.confirm_htf_account_ratio,
            )

        return signal

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
