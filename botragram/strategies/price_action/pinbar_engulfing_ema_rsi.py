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
    CandlestickMatch,
    MACDResult,
    StochRSIResult,
    calculate_atr,
    calculate_ema,
    calculate_macd,
    calculate_psar,
    calculate_rsi,
    calculate_sma,
    calculate_stoch_rsi,
    detect_engulfing,
    detect_pinbar,
    detect_star,
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
_STRONG_STAR_BONUS_RATIO: Final[Decimal] = Decimal("0.80")
_SAR_BONUS: Final[Decimal] = Decimal("0.05")
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
    rsi_long_min: Decimal = Decimal("38.0")
    rsi_long_max: Decimal = Decimal("58.0")
    rsi_short_min: Decimal = Decimal("42.0")
    rsi_short_max: Decimal = Decimal("62.0")
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
    min_trend_distance_pct: Decimal = Decimal("0.003")

    # Account Long-Short Ratio Sentiment Filter
    filter_account_ratio: bool = False
    max_long_account_ratio: Decimal = Decimal("0.75")
    min_short_account_ratio: Decimal = Decimal("0.25")
    require_account_ratio_confluence: bool = False
    confirm_htf_account_ratio: bool = False

    # Star Patterns & Parabolic SAR Configuration
    include_star_patterns: bool = True
    use_parabolic_sar: bool = True

    # MACD & Stochastic RSI Momentum & Timing Guards
    use_macd: bool = True
    macd_fast_period: int = 12
    macd_slow_period: int = 26
    macd_signal_period: int = 9
    use_stoch_rsi: bool = True
    stoch_rsi_period: int = 14
    stoch_rsi_k_period: int = 3
    stoch_rsi_d_period: int = 3
    stoch_rsi_overbought: Decimal = Decimal("80.0")
    stoch_rsi_oversold: Decimal = Decimal("20.0")

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
        if self.min_trend_distance_pct < _DECIMAL_ZERO:
            raise ValueError("Minimum trend distance percentage must not be negative")
        if (
            self.macd_fast_period <= 0
            or self.macd_slow_period <= 0
            or self.macd_signal_period <= 0
        ):
            raise ValueError("MACD periods must be positive")
        if self.macd_fast_period >= self.macd_slow_period:
            raise ValueError("MACD fast period must be less than slow period")
        if (
            self.stoch_rsi_period <= 0
            or self.stoch_rsi_k_period <= 0
            or self.stoch_rsi_d_period <= 0
        ):
            raise ValueError("Stoch RSI periods must be positive")
        if not (
            _DECIMAL_ZERO
            <= self.stoch_rsi_oversold
            < self.stoch_rsi_overbought
            <= Decimal("100.0")
        ):
            raise ValueError("Stoch RSI thresholds must be bounded within [0, 100]")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type enum identifier."""
        return StrategyType.PINBAR_ENGULFING_EMA_RSI

    @property
    def minimum_candles(self) -> int:
        """Return the minimum number of candles required for execution."""
        min_candles = max(
            self.trend_period + 2,
            self.pullback_period + 2,
            self.rsi_period + 5,
            self.volume_period + 5,
            self.atr_period + 5,
            (self.swing_lookback * 2 + 1) if self.require_key_level_location else 1,
        )
        if self.use_macd:
            min_candles = max(
                min_candles, self.macd_slow_period + self.macd_signal_period + 2
            )
        if self.use_stoch_rsi:
            min_candles = max(
                min_candles,
                self.rsi_period
                + self.stoch_rsi_period
                + self.stoch_rsi_k_period
                + self.stoch_rsi_d_period,
            )
        return min_candles

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
        if self.use_parabolic_sar:
            psar_series = calculate_psar(high_prices, low_prices)
            current_psar_uptrend: bool | None = psar_series.is_uptrend[-1]
        else:
            current_psar_uptrend = None

        macd_result: MACDResult | None = None
        if self.use_macd and len(close_prices) >= (
            self.macd_slow_period + self.macd_signal_period - 1
        ):
            macd_result = calculate_macd(
                close_prices,
                fast_period=self.macd_fast_period,
                slow_period=self.macd_slow_period,
                signal_period=self.macd_signal_period,
            )

        stoch_rsi_result: StochRSIResult | None = None
        min_stoch_candles = (
            self.rsi_period
            + self.stoch_rsi_period
            + self.stoch_rsi_k_period
            + self.stoch_rsi_d_period
            - 2
        )
        if self.use_stoch_rsi and len(close_prices) >= min_stoch_candles:
            stoch_rsi_result = calculate_stoch_rsi(
                close_prices,
                rsi_period=self.rsi_period,
                stoch_period=self.stoch_rsi_period,
                k_period=self.stoch_rsi_k_period,
                d_period=self.stoch_rsi_d_period,
            )

        curr_macd_hist: Decimal | None = None
        prev_macd_hist: Decimal | None = None
        if macd_result is not None and len(macd_result.histogram) >= 1:
            curr_macd_hist = macd_result.histogram[-1]
            prev_macd_hist = (
                macd_result.histogram[-2]
                if len(macd_result.histogram) >= 2
                else curr_macd_hist
            )

        curr_stoch_k: Decimal | None = None
        prev_stoch_k: Decimal | None = None
        curr_stoch_d: Decimal | None = None
        prev_stoch_d: Decimal | None = None
        if stoch_rsi_result is not None and len(stoch_rsi_result.k) >= 1:
            curr_stoch_k = stoch_rsi_result.k[-1]
            curr_stoch_d = stoch_rsi_result.d[-1]
            prev_stoch_k = (
                stoch_rsi_result.k[-2] if len(stoch_rsi_result.k) >= 2 else curr_stoch_k
            )
            prev_stoch_d = (
                stoch_rsi_result.d[-2] if len(stoch_rsi_result.d) >= 2 else curr_stoch_d
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
        first_star_candle = candles[-3] if len(candles) >= 3 else prev_candle

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
        if self.include_star_patterns and len(candles) >= 3:
            star = detect_star(
                first_candle=first_star_candle,
                second_candle=prev_candle,
                third_candle=curr_candle,
            )
        else:
            star = CandlestickMatch(
                matched=False,
                side=None,
                pattern_name="none",
                rejection_level=_DECIMAL_ZERO,
                body_ratio=_DECIMAL_ZERO,
                wick_ratio=_DECIMAL_ZERO,
            )

        signal_type = SignalType.HOLD
        confidence = _DECIMAL_ZERO
        reason = "No candlestick confluence pattern matched"

        # Check BUY (Long) Setup with Dual EMA Alignment
        trend_dist_long = (
            (current_close - current_trend) / current_trend
            if current_trend > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )
        uptrend_aligned = (
            current_close > current_trend
            and trend_dist_long >= self.min_trend_distance_pct
            and (not self.require_trend_filter or current_pullback >= current_trend)
        )
        if uptrend_aligned:
            pullback_proximity = current_pullback * (
                _DECIMAL_ONE + _PULLBACK_PROXIMITY_PCT
            )
            near_pullback = curr_candle.low_price <= pullback_proximity
            rsi_in_zone = self.rsi_long_min <= current_rsi <= self.rsi_long_max
            star_matched_buy = star.matched and star.side is PositionSide.LONG
            candle_trigger = (
                (pinbar.matched and pinbar.side is PositionSide.LONG)
                or (engulfing.matched and engulfing.side is PositionSide.LONG)
                or star_matched_buy
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

            # Stoch RSI Guard: avoid buying at overbought top and ensure turning up
            stoch_rsi_long_ok = True
            stoch_rsi_long_aligned = False
            if self.use_stoch_rsi and curr_stoch_k is not None:
                not_overbought = curr_stoch_k <= self.stoch_rsi_overbought
                turning_up = (
                    curr_stoch_d is not None and curr_stoch_k >= curr_stoch_d
                ) or (prev_stoch_k is not None and curr_stoch_k >= prev_stoch_k)
                stoch_rsi_long_ok = not_overbought and turning_up
                stoch_rsi_long_aligned = (
                    prev_stoch_k is not None
                    and prev_stoch_k <= self.stoch_rsi_oversold
                    and curr_stoch_k > self.stoch_rsi_oversold
                ) or (
                    prev_stoch_k is not None
                    and prev_stoch_d is not None
                    and curr_stoch_d is not None
                    and prev_stoch_k <= prev_stoch_d
                    and curr_stoch_k > curr_stoch_d
                )

            # MACD Guard: avoid buying into accelerating bearish momentum
            macd_long_ok = True
            macd_long_aligned = False
            if self.use_macd and curr_macd_hist is not None:
                macd_long_ok = (
                    prev_macd_hist is None or curr_macd_hist >= prev_macd_hist
                )
                macd_long_aligned = (
                    prev_macd_hist is not None
                    and curr_macd_hist > _DECIMAL_ZERO
                    and curr_macd_hist > prev_macd_hist
                )

            if (
                near_pullback
                and rsi_in_zone
                and volume_ok
                and candle_trigger
                and location_ok
                and stoch_rsi_long_ok
                and macd_long_ok
            ):
                if star_matched_buy:
                    pattern_label = "Morning Star"
                    pattern_low = min(
                        curr_candle.low_price,
                        prev_candle.low_price,
                        first_star_candle.low_price,
                    )
                elif pinbar.matched and pinbar.side is PositionSide.LONG:
                    pattern_label = "Bullish Pinbar"
                    pattern_low = min(curr_candle.low_price, prev_candle.low_price)
                else:
                    pattern_label = "Bullish Engulfing"
                    pattern_low = min(curr_candle.low_price, prev_candle.low_price)

                signal_type = SignalType.BUY
                confidence = self._compute_confidence(
                    pinbar_matched=pinbar.matched and pinbar.side is PositionSide.LONG,
                    pinbar_ratio=pinbar.wick_ratio,
                    engulfing_matched=engulfing.matched
                    and engulfing.side is PositionSide.LONG,
                    engulfing_ratio=engulfing.wick_ratio,
                    star_matched=star_matched_buy,
                    star_ratio=star.wick_ratio,
                    sar_aligned=current_psar_uptrend is True,
                    macd_aligned=macd_long_aligned,
                    stoch_rsi_aligned=stoch_rsi_long_aligned,
                    volume=curr_candle.volume,
                    volume_sma=current_vol_sma,
                )
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

                stoch_str = (
                    f", StochK={curr_stoch_k:.1f}" if curr_stoch_k is not None else ""
                )
                macd_str = (
                    f", MACD_h={curr_macd_hist:.4f}"
                    if curr_macd_hist is not None
                    else ""
                )
                reason = (
                    f"{pattern_label} bounce at key location "
                    f"(EMA{self.pullback_period} or Swing Low) "
                    f"in EMA{self.trend_period} uptrend "
                    f"(RSI={current_rsi:.1f}{stoch_str}{macd_str}) | "
                    f"SL: {stop_loss:.5f} | TP: {take_profit:.5f}"
                )

        # Check SELL (Short) Setup with Dual EMA Alignment
        trend_dist_short = (
            (current_trend - current_close) / current_trend
            if current_trend > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )
        downtrend_aligned = (
            current_close < current_trend
            and trend_dist_short >= self.min_trend_distance_pct
            and (not self.require_trend_filter or current_pullback <= current_trend)
        )
        if signal_type is SignalType.HOLD and downtrend_aligned:
            pullback_proximity = current_pullback * (
                _DECIMAL_ONE - _PULLBACK_PROXIMITY_PCT
            )
            near_pullback = curr_candle.high_price >= pullback_proximity
            rsi_in_zone = self.rsi_short_min <= current_rsi <= self.rsi_short_max
            star_matched_sell = star.matched and star.side is PositionSide.SHORT
            candle_trigger = (
                (pinbar.matched and pinbar.side is PositionSide.SHORT)
                or (engulfing.matched and engulfing.side is PositionSide.SHORT)
                or star_matched_sell
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

            # Stoch RSI Guard: avoid shorting at oversold bottom and ensure turning down
            stoch_rsi_short_ok = True
            stoch_rsi_short_aligned = False
            if self.use_stoch_rsi and curr_stoch_k is not None:
                not_oversold = curr_stoch_k >= self.stoch_rsi_oversold
                turning_down = (
                    curr_stoch_d is not None and curr_stoch_k <= curr_stoch_d
                ) or (prev_stoch_k is not None and curr_stoch_k <= prev_stoch_k)
                stoch_rsi_short_ok = not_oversold and turning_down
                stoch_rsi_short_aligned = (
                    prev_stoch_k is not None
                    and prev_stoch_k >= self.stoch_rsi_overbought
                    and curr_stoch_k < self.stoch_rsi_overbought
                ) or (
                    prev_stoch_k is not None
                    and prev_stoch_d is not None
                    and curr_stoch_d is not None
                    and prev_stoch_k >= prev_stoch_d
                    and curr_stoch_k < curr_stoch_d
                )

            # MACD Guard: avoid shorting into accelerating bullish momentum
            macd_short_ok = True
            macd_short_aligned = False
            if self.use_macd and curr_macd_hist is not None:
                macd_short_ok = (
                    prev_macd_hist is None or curr_macd_hist <= prev_macd_hist
                )
                macd_short_aligned = (
                    prev_macd_hist is not None
                    and curr_macd_hist < _DECIMAL_ZERO
                    and curr_macd_hist < prev_macd_hist
                )

            if (
                near_pullback
                and rsi_in_zone
                and volume_ok
                and candle_trigger
                and location_ok
                and stoch_rsi_short_ok
                and macd_short_ok
            ):
                if star_matched_sell:
                    pattern_label = "Evening Star"
                    pattern_high = max(
                        curr_candle.high_price,
                        prev_candle.high_price,
                        first_star_candle.high_price,
                    )
                elif pinbar.matched and pinbar.side is PositionSide.SHORT:
                    pattern_label = "Bearish Pinbar"
                    pattern_high = max(curr_candle.high_price, prev_candle.high_price)
                else:
                    pattern_label = "Bearish Engulfing"
                    pattern_high = max(curr_candle.high_price, prev_candle.high_price)

                signal_type = SignalType.SELL
                confidence = self._compute_confidence(
                    pinbar_matched=pinbar.matched and pinbar.side is PositionSide.SHORT,
                    pinbar_ratio=pinbar.wick_ratio,
                    engulfing_matched=engulfing.matched
                    and engulfing.side is PositionSide.SHORT,
                    engulfing_ratio=engulfing.wick_ratio,
                    star_matched=star_matched_sell,
                    star_ratio=star.wick_ratio,
                    sar_aligned=current_psar_uptrend is False,
                    macd_aligned=macd_short_aligned,
                    stoch_rsi_aligned=stoch_rsi_short_aligned,
                    volume=curr_candle.volume,
                    volume_sma=current_vol_sma,
                )
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

                stoch_str = (
                    f", StochK={curr_stoch_k:.1f}" if curr_stoch_k is not None else ""
                )
                macd_str = (
                    f", MACD_h={curr_macd_hist:.4f}"
                    if curr_macd_hist is not None
                    else ""
                )
                reason = (
                    f"{pattern_label} rejection at key location "
                    f"(EMA{self.pullback_period} or Swing High) "
                    f"in EMA{self.trend_period} downtrend "
                    f"(RSI={current_rsi:.1f}{stoch_str}{macd_str}) | "
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
        star_matched: bool = False,
        star_ratio: Decimal = _DECIMAL_ZERO,
        sar_aligned: bool = False,
        macd_aligned: bool = False,
        stoch_rsi_aligned: bool = False,
        volume: Decimal,
        volume_sma: Decimal,
    ) -> Decimal:
        """Compute composite confidence score for the detected pattern."""
        score = self.min_confidence

        if pinbar_matched and pinbar_ratio >= _STRONG_WICK_BONUS_RATIO:
            score += _CONFIDENCE_STEP_BONUS

        if engulfing_matched and engulfing_ratio >= _STRONG_ENGULFING_BONUS_RATIO:
            score += _CONFIDENCE_STEP_BONUS

        if star_matched and star_ratio >= _STRONG_STAR_BONUS_RATIO:
            score += _CONFIDENCE_STEP_BONUS

        if sar_aligned:
            score += _SAR_BONUS

        if macd_aligned:
            score += _CONFIDENCE_STEP_BONUS

        if stoch_rsi_aligned:
            score += _CONFIDENCE_STEP_BONUS

        if volume_sma > _DECIMAL_ZERO and volume >= (
            _HIGH_VOLUME_BONUS_MULTIPLIER * volume_sma
        ):
            score += _CONFIDENCE_STEP_BONUS

        return min(_MAX_CONFIDENCE, score)
