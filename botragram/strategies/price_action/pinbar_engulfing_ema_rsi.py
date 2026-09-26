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
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, PositionSide, SignalType, StrategyType
from botragram.indicators import (
    BollingerBandsResult,
    CandlestickMatch,
    MACDResult,
    StochRSIResult,
    calculate_atr,
    calculate_bollinger_bands,
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
from botragram.strategies.base import (
    BaseStrategy,
    resolve_effective_distance_pct,
    resolve_effective_natr_bounds,
    resolve_timeframe_scale_factor,
)
from botragram.utils.candle_resampler import resample_candles

__all__ = [
    "PinbarEngulfingEmaRsiStrategy",
    "check_candle_intersects_zone",
    "resolve_adaptive_htf_interval",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(
    "botragram.strategies.price_action.pinbar_engulfing_ema_rsi"
)

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_ONE: Final[Decimal] = Decimal("1")
_DEFAULT_MIN_CONFIDENCE: Final[Decimal] = Decimal("0.65")
_BASE_CONFLUENCE_SCORE: Final[Decimal] = Decimal("0.65")
_MAX_CONFIDENCE: Final[Decimal] = Decimal("0.95")
_PULLBACK_PROXIMITY_PCT: Final[Decimal] = Decimal("0.006")  # 0.6% proximity to EMA21
_HIGH_VOLUME_BONUS_MULTIPLIER: Final[Decimal] = Decimal("1.30")
_STRONG_WICK_BONUS_RATIO: Final[Decimal] = Decimal("0.70")
_STRONG_ENGULFING_BONUS_RATIO: Final[Decimal] = Decimal("1.25")
_STRONG_STAR_BONUS_RATIO: Final[Decimal] = Decimal("0.80")
_SAR_BONUS: Final[Decimal] = Decimal("0.05")
_CONFIDENCE_STEP_BONUS: Final[Decimal] = Decimal("0.05")


# =============================================================================
# Helpers
# =============================================================================
def resolve_adaptive_htf_interval(interval: Interval | None) -> Interval:
    """Resolve higher-timeframe interval adaptively for structural analysis."""
    if interval is None:
        return Interval.H1
    if interval.seconds >= 14400:
        return Interval.D1
    if interval.seconds >= 3600:
        return Interval.H4
    if interval.seconds >= 900:
        return Interval.H1
    if interval.seconds >= 300:
        return Interval.M15
    return Interval.M5


def check_candle_intersects_zone(
    *,
    low: Decimal,
    high: Decimal,
    level: Decimal | None = None,
    tolerance: Decimal | None = None,
    lower_bound: Decimal | None = None,
    upper_bound: Decimal | None = None,
) -> bool:
    """Return True if the [low, high] price range intersects the target zone.

    Zone can be specified either symmetrically via (level, tolerance) or
    asymmetrically via (lower_bound, upper_bound).

    Args:
        low: Lowest price of the evaluated candlestick.
        high: Highest price of the evaluated candlestick.
        level: Optional target reference level (e.g. EMA or swing level).
        tolerance: Optional tolerance distance around the target level.
        lower_bound: Optional explicit lower boundary of the target zone.
        upper_bound: Optional explicit upper boundary of the target zone.

    Returns:
        True if the candle range intersects the zone, False otherwise.
    """
    if lower_bound is None:
        if level is None or tolerance is None:
            raise ValueError(
                "Either (lower_bound, upper_bound) or "
                "(level, tolerance) must be provided"
            )
        lower_bound = level - tolerance
        upper_bound = level + tolerance
    elif upper_bound is None:
        raise ValueError("Both lower_bound and upper_bound must be provided")

    return low <= upper_bound and high >= lower_bound


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
    require_key_level_location: bool = True
    swing_lookback: int = 15
    location_tolerance_pct: Decimal = Decimal("0.030")
    location_atr_multiplier: Decimal | None = None
    pullback_proximity_pct: Decimal = _PULLBACK_PROXIMITY_PCT
    pullback_atr_multiplier: Decimal | None = None
    pinbar_min_range_atr: Decimal | None = None
    engulfing_min_body_atr: Decimal | None = None
    require_confirmation: bool = False

    # Structural SL/TP & Volatility/Trend Gates
    atr_period: int = 14
    atr_multiplier_sl: Decimal = Decimal("0.5")
    risk_reward_ratio: Decimal = Decimal("2.0")
    require_trend_filter: bool = True
    min_natr_threshold: Decimal = Decimal("0.0020")
    min_sl_distance_pct: Decimal = Decimal("0.0080")
    min_trend_distance_pct: Decimal = Decimal("0.003")

    # HTF Extreme Gate & Strict EMA Side Rejection
    require_htf_extreme_zone: bool = False
    htf_extreme_buffer_atr: Decimal = Decimal("0.20")
    strict_ema_side_rejection: bool = False

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

    # Dynamic Structural Target (Bollinger Bands & Resistance/Support Clearance)
    use_structural_tp: bool = True
    structural_tp_buffer_pct: Decimal = Decimal("0.002")
    min_structural_rr: Decimal = Decimal("1.0")
    bb_period: int = 20
    bb_std_dev: Decimal = Decimal("2.0")
    use_htf_structural_tp: bool = False
    htf_bb_period: int = 20
    htf_bb_std_dev: Decimal = Decimal("2.0")

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
        if self.htf_extreme_buffer_atr < _DECIMAL_ZERO:
            raise ValueError("HTF extreme buffer ATR must not be negative")
        if self.swing_lookback <= 2:
            raise ValueError("Swing lookback must be greater than 2")
        if self.location_tolerance_pct < _DECIMAL_ZERO:
            raise ValueError("Location tolerance percentage must not be negative")
        if (
            self.location_atr_multiplier is not None
            and self.location_atr_multiplier <= _DECIMAL_ZERO
        ):
            raise ValueError("Location ATR multiplier must be positive")
        if self.pullback_proximity_pct < _DECIMAL_ZERO:
            raise ValueError("Pullback proximity percentage must not be negative")
        if (
            self.pullback_atr_multiplier is not None
            and self.pullback_atr_multiplier <= _DECIMAL_ZERO
        ):
            raise ValueError("Pullback ATR multiplier must be positive")
        if (
            self.pinbar_min_range_atr is not None
            and self.pinbar_min_range_atr <= _DECIMAL_ZERO
        ):
            raise ValueError("Pinbar minimum range ATR multiplier must be positive")
        if (
            self.engulfing_min_body_atr is not None
            and self.engulfing_min_body_atr <= _DECIMAL_ZERO
        ):
            raise ValueError("Engulfing minimum body ATR multiplier must be positive")
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
        if self.structural_tp_buffer_pct < _DECIMAL_ZERO:
            raise ValueError("Structural TP buffer percentage must not be negative")
        if self.min_structural_rr <= _DECIMAL_ZERO:
            raise ValueError("Minimum structural RR must be positive")
        if self.bb_period <= 0 or self.bb_std_dev <= _DECIMAL_ZERO:
            raise ValueError("Bollinger Bands parameters must be positive")
        if self.htf_bb_period <= 0 or self.htf_bb_std_dev <= _DECIMAL_ZERO:
            raise ValueError("HTF Bollinger Bands parameters must be positive")

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
        if self.use_structural_tp:
            min_candles = max(min_candles, self.bb_period + 2)
        if self.require_confirmation:
            min_candles += 1
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

        bb_result: BollingerBandsResult | None = None
        if self.use_structural_tp and len(close_prices) >= self.bb_period:
            bb_result = calculate_bollinger_bands(
                close_prices,
                period=self.bb_period,
                standard_deviation=self.bb_std_dev,
            )

        htf_upper_bb: Decimal | None = None
        htf_lower_bb: Decimal | None = None
        htf_swing_high: Decimal | None = None
        htf_swing_low: Decimal | None = None
        htf_atr: Decimal | None = None

        htf_target_interval = resolve_adaptive_htf_interval(candles[-1].interval)

        if (
            self.require_htf_extreme_zone
            or (self.use_structural_tp and self.use_htf_structural_tp)
        ) and len(candles) >= 8:
            try:
                htf_candles = resample_candles(
                    candles=candles,
                    target_interval=htf_target_interval,
                    closed_only=True,
                )
                if len(htf_candles) >= self.htf_bb_period:
                    htf_close_prices = tuple(c.close_price for c in htf_candles)
                    htf_high_prices = tuple(c.high_price for c in htf_candles)
                    htf_low_prices = tuple(c.low_price for c in htf_candles)
                    htf_bb = calculate_bollinger_bands(
                        htf_close_prices,
                        period=self.htf_bb_period,
                        standard_deviation=self.htf_bb_std_dev,
                    )
                    htf_upper_bb = htf_bb.upper[-1]
                    htf_lower_bb = htf_bb.lower[-1]
                    htf_atr_res = calculate_atr(
                        htf_high_prices,
                        htf_low_prices,
                        htf_close_prices,
                        period=min(self.atr_period, len(htf_close_prices) - 1),
                    )
                    htf_atr = htf_atr_res[-1] if htf_atr_res else None
                if htf_candles:
                    recent_htf = htf_candles[-min(len(htf_candles), 10) :]
                    htf_swing_high = max(c.high_price for c in recent_htf)
                    htf_swing_low = min(c.low_price for c in recent_htf)
            except (ValueError, TypeError, IndexError) as exc:
                _LOGGER.debug(
                    "HTF candle resampling or indicator calculation bypassed: %s",
                    exc,
                )
                htf_upper_bb = None
                htf_lower_bb = None
                htf_atr = None

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

        if self.require_confirmation:
            setup_candle = prev_candle
            setup_prev_candle = first_star_candle
            setup_first_star = candles[-4] if len(candles) >= 4 else setup_prev_candle
        else:
            setup_candle = curr_candle
            setup_prev_candle = prev_candle
            setup_first_star = first_star_candle

        current_close = curr_candle.close_price
        current_trend = ema_trend[-1]
        current_pullback = ema_pullback[-1]
        current_rsi = rsi_series[-1]
        current_vol_sma = volume_sma[-1]
        current_atr = atr_series[-1]

        eff_min_natr, _ = resolve_effective_natr_bounds(
            curr_candle.symbol,
            self.min_natr_threshold,
            interval=curr_candle.interval,
        )
        eff_min_sl_pct, eff_min_trend_pct = resolve_effective_distance_pct(
            curr_candle.symbol,
            self.min_sl_distance_pct,
            self.min_trend_distance_pct,
            interval=curr_candle.interval,
        )
        scale_factor = resolve_timeframe_scale_factor(curr_candle.interval)
        eff_structural_tp_buffer_pct = self.structural_tp_buffer_pct * scale_factor

        # HARD GATE: Volatility Gate (reject dead market)
        if (
            current_close > _DECIMAL_ZERO
            and (current_atr / current_close) < eff_min_natr
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
                    f"{eff_min_natr:.4f})"
                ),
            )

        # SOFT CONFIRMATION: Volume expansion confirmation
        volume_ok = curr_candle.volume >= (self.volume_multiplier * current_vol_sma)

        # HARD GATE: Candlestick pattern detection on setup candle
        pinbar = detect_pinbar(
            candle=setup_candle,
            min_wick_ratio=self.min_wick_ratio,
            max_opposite_wick_ratio=self.max_opposite_wick_ratio,
            min_range_atr=self.pinbar_min_range_atr,
            atr=current_atr,
        )
        engulfing = detect_engulfing(
            prev_candle=setup_prev_candle,
            curr_candle=setup_candle,
            min_body_ratio=self.min_engulfing_body_ratio,
            min_body_atr=self.engulfing_min_body_atr,
            atr=current_atr,
        )
        if self.include_star_patterns and (
            len(candles) >= 4 if self.require_confirmation else len(candles) >= 3
        ):
            star = detect_star(
                first_candle=setup_first_star,
                second_candle=setup_prev_candle,
                third_candle=setup_candle,
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
        stop_loss: Decimal | None = None
        take_profit: Decimal | None = None

        pullback_tolerance = (
            self.pullback_atr_multiplier * current_atr
            if self.pullback_atr_multiplier is not None
            and self.pullback_atr_multiplier > _DECIMAL_ZERO
            else current_pullback * self.pullback_proximity_pct
        )
        location_tolerance = (
            self.location_atr_multiplier * current_atr
            if self.location_atr_multiplier is not None
            and self.location_atr_multiplier > _DECIMAL_ZERO
            else current_pullback * self.location_tolerance_pct
        )

        # Check BUY (Long) Setup with Dual EMA Alignment
        trend_dist_long = (
            (current_close - current_trend) / current_trend
            if current_trend > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )
        uptrend_aligned = (
            current_close > current_trend
            and trend_dist_long >= eff_min_trend_pct
            and (not self.require_trend_filter or current_pullback >= current_trend)
        )
        if uptrend_aligned:
            # HARD GATE: Two-sided pullback intersection with EMA21 zone
            long_pullback_upper = current_pullback + pullback_tolerance
            long_pullback_lower = current_pullback - location_tolerance
            near_pullback = check_candle_intersects_zone(
                low=setup_candle.low_price,
                high=setup_candle.high_price,
                lower_bound=long_pullback_lower,
                upper_bound=long_pullback_upper,
            )

            # SOFT CONFIRMATION: RSI in pullback range
            rsi_in_zone = self.rsi_long_min <= current_rsi <= self.rsi_long_max

            # HARD GATE: Candlestick trigger (direct close or confirmation breakout)
            star_matched_buy = star.matched and star.side is PositionSide.LONG
            pattern_matched_buy = (
                (pinbar.matched and pinbar.side is PositionSide.LONG)
                or (engulfing.matched and engulfing.side is PositionSide.LONG)
                or star_matched_buy
            )
            if self.require_confirmation:
                candle_trigger = (
                    pattern_matched_buy
                    and curr_candle.close_price > setup_candle.high_price
                )
            else:
                candle_trigger = pattern_matched_buy

            # HARD GATE: Key level location check (Dynamic EMA Support or Swing Low)
            at_ema_support = check_candle_intersects_zone(
                low=setup_candle.low_price,
                high=setup_candle.high_price,
                level=current_pullback,
                tolerance=location_tolerance,
            )
            at_swing_support = (
                last_swing_low is not None
                and check_candle_intersects_zone(
                    low=setup_candle.low_price,
                    high=setup_candle.high_price,
                    level=last_swing_low,
                    tolerance=location_tolerance,
                )
            )
            location_ok = (
                not self.require_key_level_location
                or at_ema_support
                or at_swing_support
            )

            # SOFT CONFIRMATION: Stoch RSI Guard
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

            # SOFT CONFIRMATION: MACD Guard
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

            # HARD GATE: Strict EMA rejection (candle close must be >= EMA21)
            ema_side_long_ok = (
                not self.strict_ema_side_rejection
                or setup_candle.close_price >= current_pullback
            )

            # HARD GATE: HTF Extreme Lower Zone (fail-closed if HTF data unavailable)
            if self.require_htf_extreme_zone:
                if htf_lower_bb is None:
                    htf_extreme_long_ok = False
                else:
                    eff_htf_atr = htf_atr if htf_atr is not None else current_atr
                    htf_lower_limit = htf_lower_bb + (
                        self.htf_extreme_buffer_atr * eff_htf_atr
                    )
                    htf_extreme_long_ok = setup_candle.low_price <= htf_lower_limit
            else:
                htf_extreme_long_ok = True

            if (
                near_pullback
                and rsi_in_zone
                and volume_ok
                and candle_trigger
                and location_ok
                and ema_side_long_ok
                and htf_extreme_long_ok
                and stoch_rsi_long_ok
                and macd_long_ok
            ):
                if star_matched_buy:
                    pattern_label = "Morning Star"
                    pattern_low = min(
                        curr_candle.low_price,
                        setup_candle.low_price,
                        setup_prev_candle.low_price,
                        setup_first_star.low_price,
                    )
                elif pinbar.matched and pinbar.side is PositionSide.LONG:
                    pattern_label = "Bullish Pinbar"
                    pattern_low = min(
                        curr_candle.low_price,
                        setup_candle.low_price,
                        setup_prev_candle.low_price,
                    )
                else:
                    pattern_label = "Bullish Engulfing"
                    pattern_low = min(
                        curr_candle.low_price,
                        setup_candle.low_price,
                        setup_prev_candle.low_price,
                    )

                signal_type = SignalType.BUY
                confidence = self._compute_confidence(
                    pinbar_matched=pinbar.matched and pinbar.side is PositionSide.LONG,
                    pinbar_ratio=pinbar.pattern_ratio or pinbar.wick_ratio,
                    engulfing_matched=engulfing.matched
                    and engulfing.side is PositionSide.LONG,
                    engulfing_ratio=engulfing.pattern_ratio or engulfing.wick_ratio,
                    star_matched=star_matched_buy,
                    star_ratio=star.pattern_ratio or star.wick_ratio,
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

                min_risk_dist = current_close * eff_min_sl_pct
                if risk_dist < min_risk_dist:
                    risk_dist = min_risk_dist
                    stop_loss = current_close - risk_dist

                take_profit = current_close + (risk_dist * self.risk_reward_ratio)
                reason_extra = ""

                if self.use_structural_tp:
                    walls: list[tuple[Decimal, str]] = []
                    if bb_result is not None:
                        curr_upper_bb = bb_result.upper[-1]
                        if curr_upper_bb > current_close:
                            int_label = curr_candle.interval.value
                            walls.append(
                                (
                                    curr_upper_bb,
                                    f"{int_label} Upper BB={curr_upper_bb:.4f}",
                                )
                            )
                    if htf_upper_bb is not None and htf_upper_bb > current_close:
                        htf_lbl = f"{htf_target_interval.value} Upper BB"
                        walls.append((htf_upper_bb, f"{htf_lbl}={htf_upper_bb:.4f}"))
                    if htf_swing_high is not None and htf_swing_high > current_close:
                        htf_lbl = f"{htf_target_interval.value} Swing High"
                        walls.append(
                            (htf_swing_high, f"{htf_lbl}={htf_swing_high:.4f}")
                        )

                    if walls:
                        nearest_wall, wall_name = min(walls, key=lambda w: w[0])
                        if take_profit > nearest_wall:
                            trimmed_tp = nearest_wall * (
                                _DECIMAL_ONE - eff_structural_tp_buffer_pct
                            )
                            eff_rr = (trimmed_tp - current_close) / risk_dist
                            if eff_rr < self.min_structural_rr:
                                signal_type = SignalType.HOLD
                                confidence = _DECIMAL_ZERO
                                stop_loss = None
                                take_profit = None
                                reason = (
                                    f"BUY setup rejected: Structural resistance "
                                    f"({wall_name}) restricts TP "
                                    f"(trimmed RR={eff_rr:.2f} < "
                                    f"{self.min_structural_rr:.2f})"
                                )
                            else:
                                take_profit = trimmed_tp
                                reason_extra = (
                                    f" | Structural TP trimmed to {take_profit:.5f} "
                                    f"({wall_name}, RR: {eff_rr:.2f})"
                                )
                    else:
                        reason_extra = ""
                else:
                    reason_extra = ""

                if signal_type is not SignalType.HOLD:
                    stoch_str = (
                        f", StochK={curr_stoch_k:.1f}"
                        if curr_stoch_k is not None
                        else ""
                    )
                    macd_str = (
                        f", MACD_h={curr_macd_hist:.4f}"
                        if curr_macd_hist is not None
                        else ""
                    )
                    mode_str = " (Confirmed)" if self.require_confirmation else ""
                    reason = (
                        f"{pattern_label}{mode_str} bounce at key location "
                        f"(EMA{self.pullback_period} or Swing Low) "
                        f"in EMA{self.trend_period} uptrend "
                        f"(RSI={current_rsi:.1f}{stoch_str}{macd_str}) | "
                        f"SL: {stop_loss:.5f} | TP: {take_profit:.5f}{reason_extra}"
                    )

        # Check SELL (Short) Setup with Dual EMA Alignment
        trend_dist_short = (
            (current_trend - current_close) / current_trend
            if current_trend > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )
        downtrend_aligned = (
            current_close < current_trend
            and trend_dist_short >= eff_min_trend_pct
            and (not self.require_trend_filter or current_pullback <= current_trend)
        )
        if signal_type is SignalType.HOLD and downtrend_aligned:
            # HARD GATE: Two-sided pullback intersection with EMA21 zone
            short_pullback_lower = current_pullback - pullback_tolerance
            short_pullback_upper = current_pullback + location_tolerance
            near_pullback = check_candle_intersects_zone(
                low=setup_candle.low_price,
                high=setup_candle.high_price,
                lower_bound=short_pullback_lower,
                upper_bound=short_pullback_upper,
            )

            # SOFT CONFIRMATION: RSI in pullback range
            rsi_in_zone = self.rsi_short_min <= current_rsi <= self.rsi_short_max

            # HARD GATE: Candlestick trigger (direct close or confirmation breakout)
            star_matched_sell = star.matched and star.side is PositionSide.SHORT
            pattern_matched_sell = (
                (pinbar.matched and pinbar.side is PositionSide.SHORT)
                or (engulfing.matched and engulfing.side is PositionSide.SHORT)
                or star_matched_sell
            )
            if self.require_confirmation:
                candle_trigger = (
                    pattern_matched_sell
                    and curr_candle.close_price < setup_candle.low_price
                )
            else:
                candle_trigger = pattern_matched_sell

            # HARD GATE: Key level location check (Dynamic EMA Resistance or Swing High)
            at_ema_resistance = check_candle_intersects_zone(
                low=setup_candle.low_price,
                high=setup_candle.high_price,
                level=current_pullback,
                tolerance=location_tolerance,
            )
            at_swing_resistance = (
                last_swing_high is not None
                and check_candle_intersects_zone(
                    low=setup_candle.low_price,
                    high=setup_candle.high_price,
                    level=last_swing_high,
                    tolerance=location_tolerance,
                )
            )
            location_ok = (
                not self.require_key_level_location
                or at_ema_resistance
                or at_swing_resistance
            )

            # SOFT CONFIRMATION: Stoch RSI Guard
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

            # SOFT CONFIRMATION: MACD Guard
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

            # HARD GATE: Strict EMA rejection (candle close must be <= EMA21)
            ema_side_short_ok = (
                not self.strict_ema_side_rejection
                or setup_candle.close_price <= current_pullback
            )

            # HARD GATE: HTF Extreme Upper Zone (fail-closed if HTF data unavailable)
            if self.require_htf_extreme_zone:
                if htf_upper_bb is None:
                    htf_extreme_short_ok = False
                else:
                    eff_htf_atr = htf_atr if htf_atr is not None else current_atr
                    htf_upper_limit = htf_upper_bb - (
                        self.htf_extreme_buffer_atr * eff_htf_atr
                    )
                    htf_extreme_short_ok = setup_candle.high_price >= htf_upper_limit
            else:
                htf_extreme_short_ok = True

            if (
                near_pullback
                and rsi_in_zone
                and volume_ok
                and candle_trigger
                and location_ok
                and ema_side_short_ok
                and htf_extreme_short_ok
                and stoch_rsi_short_ok
                and macd_short_ok
            ):
                if star_matched_sell:
                    pattern_label = "Evening Star"
                    pattern_high = max(
                        curr_candle.high_price,
                        setup_candle.high_price,
                        setup_prev_candle.high_price,
                        setup_first_star.high_price,
                    )
                elif pinbar.matched and pinbar.side is PositionSide.SHORT:
                    pattern_label = "Bearish Pinbar"
                    pattern_high = max(
                        curr_candle.high_price,
                        setup_candle.high_price,
                        setup_prev_candle.high_price,
                    )
                else:
                    pattern_label = "Bearish Engulfing"
                    pattern_high = max(
                        curr_candle.high_price,
                        setup_candle.high_price,
                        setup_prev_candle.high_price,
                    )

                signal_type = SignalType.SELL
                confidence = self._compute_confidence(
                    pinbar_matched=pinbar.matched and pinbar.side is PositionSide.SHORT,
                    pinbar_ratio=pinbar.pattern_ratio or pinbar.wick_ratio,
                    engulfing_matched=engulfing.matched
                    and engulfing.side is PositionSide.SHORT,
                    engulfing_ratio=engulfing.pattern_ratio or engulfing.wick_ratio,
                    star_matched=star_matched_sell,
                    star_ratio=star.pattern_ratio or star.wick_ratio,
                    sar_aligned=current_psar_uptrend is False,
                    macd_aligned=macd_short_aligned,
                    stoch_rsi_aligned=stoch_rsi_short_aligned,
                    volume=curr_candle.volume,
                    volume_sma=current_vol_sma,
                )
                stop_loss = pattern_high + (self.atr_multiplier_sl * current_atr)
                risk_dist = stop_loss - current_close
                if risk_dist <= _DECIMAL_ZERO:
                    stop_loss = current_close + (self.atr_multiplier_sl * current_atr)
                    risk_dist = self.atr_multiplier_sl * current_atr

                min_risk_dist = current_close * eff_min_sl_pct
                if risk_dist < min_risk_dist:
                    risk_dist = min_risk_dist
                    stop_loss = current_close + risk_dist

                take_profit = current_close - (risk_dist * self.risk_reward_ratio)
                reason_extra = ""

                if self.use_structural_tp:
                    floors: list[tuple[Decimal, str]] = []
                    if bb_result is not None:
                        curr_lower_bb = bb_result.lower[-1]
                        if curr_lower_bb < current_close:
                            int_label = curr_candle.interval.value
                            floors.append(
                                (
                                    curr_lower_bb,
                                    f"{int_label} Lower BB={curr_lower_bb:.4f}",
                                )
                            )
                    if htf_lower_bb is not None and htf_lower_bb < current_close:
                        htf_lbl = f"{htf_target_interval.value} Lower BB"
                        floors.append((htf_lower_bb, f"{htf_lbl}={htf_lower_bb:.4f}"))
                    if htf_swing_low is not None and htf_swing_low < current_close:
                        htf_lbl = f"{htf_target_interval.value} Swing Low"
                        floors.append((htf_swing_low, f"{htf_lbl}={htf_swing_low:.4f}"))

                    if floors:
                        nearest_floor, floor_name = max(floors, key=lambda f: f[0])
                        if take_profit < nearest_floor:
                            trimmed_tp = nearest_floor * (
                                _DECIMAL_ONE + eff_structural_tp_buffer_pct
                            )
                            eff_rr = (current_close - trimmed_tp) / risk_dist
                            if eff_rr < self.min_structural_rr:
                                signal_type = SignalType.HOLD
                                confidence = _DECIMAL_ZERO
                                stop_loss = None
                                take_profit = None
                                reason = (
                                    f"SELL setup rejected: Structural support "
                                    f"({floor_name}) restricts TP "
                                    f"(trimmed RR={eff_rr:.2f} < "
                                    f"{self.min_structural_rr:.2f})"
                                )
                            else:
                                take_profit = trimmed_tp
                                reason_extra = (
                                    f" | Structural TP trimmed to {take_profit:.5f} "
                                    f"({floor_name}, RR: {eff_rr:.2f})"
                                )
                    else:
                        reason_extra = ""
                else:
                    reason_extra = ""

                if signal_type is not SignalType.HOLD:
                    stoch_str = (
                        f", StochK={curr_stoch_k:.1f}"
                        if curr_stoch_k is not None
                        else ""
                    )
                    macd_str = (
                        f", MACD_h={curr_macd_hist:.4f}"
                        if curr_macd_hist is not None
                        else ""
                    )
                    mode_str = " (Confirmed)" if self.require_confirmation else ""
                    reason = (
                        f"{pattern_label}{mode_str} rejection at key location "
                        f"(EMA{self.pullback_period} or Swing High) "
                        f"in EMA{self.trend_period} downtrend "
                        f"(RSI={current_rsi:.1f}{stoch_str}{macd_str}) | "
                        f"SL: {stop_loss:.5f} | TP: {take_profit:.5f}{reason_extra}"
                    )

        signal = Signal(
            symbol=curr_candle.symbol,
            signal_type=signal_type,
            price=curr_candle.close_price,
            confidence=confidence,
            strategy_name=self.strategy_type.value,
            generated_at=curr_candle.close_time,
            reason=reason,
            stop_loss=stop_loss if signal_type is not SignalType.HOLD else None,
            take_profit=take_profit if signal_type is not SignalType.HOLD else None,
        )

        if (
            signal.signal_type is not SignalType.HOLD
            and signal.confidence < self.min_confidence
        ):
            return replace(
                signal,
                signal_type=SignalType.HOLD,
                confidence=signal.confidence,
                reason=(
                    f"[REJECTED_CONFIDENCE] Confidence {signal.confidence:.2f} below "
                    f"minimum threshold {self.min_confidence:.2f} "
                    f"(originally {signal.signal_type.value})"
                ),
            )

        return signal

    def detect_zone_candidate(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal | None:
        """Detect whether market state qualifies as a Stage 1 zone candidate.

        Stage 1 requirements:
        - SHORT:
          1. Downtrend aligned (close < trend and pullback <= trend if filtered).
          2. Price at HTF upper extreme zone (fail-closed if HTF BB missing).
          3. Price at local structural resistance (EMA21 and/or swing high).
          4. Safe volatility (NATR >= min_natr_threshold).
        - LONG (mirror):
          1. Uptrend aligned (close > trend and pullback >= trend if filtered).
          2. Price at HTF lower extreme zone (fail-closed if HTF BB missing).
          3. Price at local structural support (EMA21 and/or swing low).
          4. Safe volatility (NATR >= min_natr_threshold).

        Returns:
            Signal with signal_type=HOLD and reason [STALKING_ZONE_...] if in zone,
            or None if not qualified.
        """
        self.validate_candles(candles=candles)

        close_prices = tuple(c.close_price for c in candles)
        high_prices = tuple(c.high_price for c in candles)
        low_prices = tuple(c.low_price for c in candles)

        ema_trend = calculate_ema(close_prices, period=self.trend_period)
        ema_pullback = calculate_ema(close_prices, period=self.pullback_period)
        atr_series = calculate_atr(
            high_prices,
            low_prices,
            close_prices,
            period=self.atr_period,
        )

        curr_candle = candles[-1]
        current_close = curr_candle.close_price
        current_trend = ema_trend[-1]
        current_pullback = ema_pullback[-1]
        current_atr = atr_series[-1]

        eff_min_natr, _ = resolve_effective_natr_bounds(
            curr_candle.symbol,
            self.min_natr_threshold,
            interval=curr_candle.interval,
        )
        eff_min_sl_pct, eff_min_trend_pct = resolve_effective_distance_pct(
            curr_candle.symbol,
            self.min_sl_distance_pct,
            self.min_trend_distance_pct,
            interval=curr_candle.interval,
        )

        # Volatility check: fail-closed if dead market
        if (
            current_close <= _DECIMAL_ZERO
            or (current_atr / current_close) < eff_min_natr
        ):
            return None

        # Resolve HTF extreme levels
        htf_upper_bb: Decimal | None = None
        htf_lower_bb: Decimal | None = None
        htf_atr: Decimal | None = None
        htf_target_interval = resolve_adaptive_htf_interval(curr_candle.interval)

        volume_series = tuple(c.volume for c in candles)
        vol_window = min(20, len(volume_series))
        volume_sma_series = (
            calculate_sma(volume_series, period=vol_window) if vol_window > 0 else ()
        )
        current_volume_sma = (
            volume_sma_series[-1] if volume_sma_series else _DECIMAL_ZERO
        )

        rsi_window = min(self.rsi_period, len(close_prices) - 1)
        rsi_series = (
            calculate_rsi(close_prices, period=rsi_window) if rsi_window >= 2 else ()
        )
        current_rsi = rsi_series[-1] if rsi_series else None

        if self.require_htf_extreme_zone and len(candles) >= 8:
            try:
                htf_candles = resample_candles(
                    candles=candles,
                    target_interval=htf_target_interval,
                    closed_only=True,
                )
                if len(htf_candles) >= self.htf_bb_period:
                    htf_close_prices = tuple(c.close_price for c in htf_candles)
                    htf_high_prices = tuple(c.high_price for c in htf_candles)
                    htf_low_prices = tuple(c.low_price for c in htf_candles)
                    htf_bb = calculate_bollinger_bands(
                        htf_close_prices,
                        period=self.htf_bb_period,
                        standard_deviation=self.htf_bb_std_dev,
                    )
                    htf_upper_bb = htf_bb.upper[-1]
                    htf_lower_bb = htf_bb.lower[-1]
                    htf_atr_res = calculate_atr(
                        htf_high_prices,
                        htf_low_prices,
                        htf_close_prices,
                        period=min(self.atr_period, len(htf_close_prices) - 1),
                    )
                    htf_atr = htf_atr_res[-1] if htf_atr_res else None
            except (ValueError, TypeError, IndexError) as exc:
                _LOGGER.debug(
                    "HTF candle resampling or indicator calculation bypassed: %s",
                    exc,
                )
                htf_upper_bb = None
                htf_lower_bb = None
                htf_atr = None

        if self.require_key_level_location:
            last_swing_high, last_swing_low = find_swing_levels(
                high_prices=high_prices[:-1],
                low_prices=low_prices[:-1],
                swing_window=self.swing_lookback,
            )
        else:
            last_swing_high, last_swing_low = None, None

        pullback_tolerance = (
            self.pullback_atr_multiplier * current_atr
            if self.pullback_atr_multiplier is not None
            and self.pullback_atr_multiplier > _DECIMAL_ZERO
            else current_pullback * self.pullback_proximity_pct
        )
        location_tolerance = (
            self.location_atr_multiplier * current_atr
            if self.location_atr_multiplier is not None
            and self.location_atr_multiplier > _DECIMAL_ZERO
            else current_pullback * self.location_tolerance_pct
        )

        # 1. Evaluate SHORT Zone Candidate
        trend_dist_short = (
            (current_trend - current_close) / current_trend
            if current_trend > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )
        downtrend_aligned = (
            current_close < current_trend
            and trend_dist_short >= eff_min_trend_pct
            and (not self.require_trend_filter or current_pullback <= current_trend)
        )
        if downtrend_aligned:
            if self.require_htf_extreme_zone:
                if htf_upper_bb is None:
                    htf_extreme_short_ok = False
                else:
                    eff_htf_atr = htf_atr if htf_atr is not None else current_atr
                    htf_upper_limit = htf_upper_bb - (
                        self.htf_extreme_buffer_atr * eff_htf_atr
                    )
                    htf_extreme_short_ok = curr_candle.high_price >= htf_upper_limit
            else:
                htf_extreme_short_ok = True

            short_pullback_lower = current_pullback - pullback_tolerance
            short_pullback_upper = current_pullback + location_tolerance
            near_pullback = check_candle_intersects_zone(
                low=curr_candle.low_price,
                high=curr_candle.high_price,
                lower_bound=short_pullback_lower,
                upper_bound=short_pullback_upper,
            )
            at_ema_resistance = check_candle_intersects_zone(
                low=curr_candle.low_price,
                high=curr_candle.high_price,
                level=current_pullback,
                tolerance=location_tolerance,
            )
            at_swing_resistance = (
                last_swing_high is not None
                and check_candle_intersects_zone(
                    low=curr_candle.low_price,
                    high=curr_candle.high_price,
                    level=last_swing_high,
                    tolerance=location_tolerance,
                )
            )
            structural_upper_ok = (
                near_pullback or at_ema_resistance or at_swing_resistance
            )

            if htf_extreme_short_ok and structural_upper_ok:
                invalidation_price = max(
                    curr_candle.high_price,
                    current_pullback + location_tolerance,
                )
                stop_loss = invalidation_price + (self.atr_multiplier_sl * current_atr)
                risk_dist = stop_loss - current_close
                min_risk_dist = current_close * eff_min_sl_pct
                if risk_dist < min_risk_dist:
                    risk_dist = min_risk_dist
                    stop_loss = current_close + risk_dist
                take_profit = current_close - (risk_dist * self.risk_reward_ratio)
                htf_lbl = f"{htf_target_interval.value} Upper BB"
                eff_htf_atr = htf_atr if htf_atr is not None else current_atr
                htf_depth = (
                    (curr_candle.high_price - htf_upper_bb) / eff_htf_atr
                    if htf_upper_bb is not None
                    and eff_htf_atr > _DECIMAL_ZERO
                    and curr_candle.high_price >= htf_upper_bb
                    else _DECIMAL_ZERO
                )
                confidence = self.compute_zone_confidence(
                    side=PositionSide.SHORT,
                    current_candle=curr_candle,
                    trend_distance_pct=trend_dist_short,
                    eff_min_trend_pct=eff_min_trend_pct,
                    htf_extreme_depth=htf_depth,
                    at_ema=at_ema_resistance,
                    at_swing=at_swing_resistance,
                    volume=curr_candle.volume,
                    volume_sma=current_volume_sma,
                    rsi=current_rsi,
                )
                return Signal(
                    symbol=curr_candle.symbol,
                    signal_type=SignalType.HOLD,
                    price=current_close,
                    confidence=confidence,
                    strategy_name=self.strategy_type.value,
                    generated_at=curr_candle.close_time,
                    reason=(
                        f"[STALKING_ZONE_SHORT] Price in {htf_lbl} & "
                        f"local resistance (EMA{self.pullback_period}) "
                        f"in EMA{self.trend_period} downtrend"
                    ),
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )

        # 2. Evaluate LONG Zone Candidate (Mirror)
        trend_dist_long = (
            (current_close - current_trend) / current_trend
            if current_trend > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )
        uptrend_aligned = (
            current_close > current_trend
            and trend_dist_long >= eff_min_trend_pct
            and (not self.require_trend_filter or current_pullback >= current_trend)
        )
        if uptrend_aligned:
            if self.require_htf_extreme_zone:
                if htf_lower_bb is None:
                    htf_extreme_long_ok = False
                else:
                    eff_htf_atr = htf_atr if htf_atr is not None else current_atr
                    htf_lower_limit = htf_lower_bb + (
                        self.htf_extreme_buffer_atr * eff_htf_atr
                    )
                    htf_extreme_long_ok = curr_candle.low_price <= htf_lower_limit
            else:
                htf_extreme_long_ok = True

            long_pullback_upper = current_pullback + pullback_tolerance
            long_pullback_lower = current_pullback - location_tolerance
            near_pullback = check_candle_intersects_zone(
                low=curr_candle.low_price,
                high=curr_candle.high_price,
                lower_bound=long_pullback_lower,
                upper_bound=long_pullback_upper,
            )
            at_ema_support = check_candle_intersects_zone(
                low=curr_candle.low_price,
                high=curr_candle.high_price,
                level=current_pullback,
                tolerance=location_tolerance,
            )
            at_swing_support = (
                last_swing_low is not None
                and check_candle_intersects_zone(
                    low=curr_candle.low_price,
                    high=curr_candle.high_price,
                    level=last_swing_low,
                    tolerance=location_tolerance,
                )
            )
            structural_lower_ok = near_pullback or at_ema_support or at_swing_support

            if htf_extreme_long_ok and structural_lower_ok:
                invalidation_price = min(
                    curr_candle.low_price,
                    current_pullback - location_tolerance,
                )
                stop_loss = invalidation_price - (self.atr_multiplier_sl * current_atr)
                risk_dist = current_close - stop_loss
                min_risk_dist = current_close * eff_min_sl_pct
                if risk_dist < min_risk_dist:
                    risk_dist = min_risk_dist
                    stop_loss = current_close - risk_dist
                take_profit = current_close + (risk_dist * self.risk_reward_ratio)
                htf_lbl = f"{htf_target_interval.value} Lower BB"
                eff_htf_atr = htf_atr if htf_atr is not None else current_atr
                htf_depth = (
                    (htf_lower_bb - curr_candle.low_price) / eff_htf_atr
                    if htf_lower_bb is not None
                    and eff_htf_atr > _DECIMAL_ZERO
                    and curr_candle.low_price <= htf_lower_bb
                    else _DECIMAL_ZERO
                )
                confidence = self.compute_zone_confidence(
                    side=PositionSide.LONG,
                    current_candle=curr_candle,
                    trend_distance_pct=trend_dist_long,
                    eff_min_trend_pct=eff_min_trend_pct,
                    htf_extreme_depth=htf_depth,
                    at_ema=at_ema_support,
                    at_swing=at_swing_support,
                    volume=curr_candle.volume,
                    volume_sma=current_volume_sma,
                    rsi=current_rsi,
                )
                return Signal(
                    symbol=curr_candle.symbol,
                    signal_type=SignalType.HOLD,
                    price=current_close,
                    confidence=confidence,
                    strategy_name=self.strategy_type.value,
                    generated_at=curr_candle.close_time,
                    reason=(
                        f"[STALKING_ZONE_LONG] Price in {htf_lbl} & "
                        f"local support (EMA{self.pullback_period}) "
                        f"in EMA{self.trend_period} uptrend"
                    ),
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )

        return None

    def compute_zone_confidence(
        self,
        *,
        side: PositionSide,
        current_candle: Candle,
        trend_distance_pct: Decimal,
        eff_min_trend_pct: Decimal,
        htf_extreme_depth: Decimal,
        at_ema: bool,
        at_swing: bool,
        volume: Decimal,
        volume_sma: Decimal,
        rsi: Decimal | None = None,
    ) -> Decimal:
        """Compute dynamic quality-based confidence score for Stage 1 zone setup."""
        score = self.min_confidence

        # 1. HTF Extreme Zone penetration depth
        if htf_extreme_depth >= Decimal("0.5"):
            score += Decimal("0.08")
        elif htf_extreme_depth > _DECIMAL_ZERO:
            score += Decimal("0.04")

        # 2. Strong trend alignment
        if (
            eff_min_trend_pct > _DECIMAL_ZERO
            and trend_distance_pct >= eff_min_trend_pct * Decimal("1.5")
        ):
            score += Decimal("0.06")
        elif trend_distance_pct > eff_min_trend_pct:
            score += Decimal("0.03")

        # 3. Structural confluence (both EMA and Swing level aligned)
        if at_ema and at_swing:
            score += Decimal("0.06")
        elif at_ema or at_swing:
            score += Decimal("0.03")

        # 4. RSI extreme alignment in pullback
        if rsi is not None:
            if side is PositionSide.SHORT and rsi >= Decimal("65"):
                score += Decimal("0.05")
            elif side is PositionSide.LONG and rsi <= Decimal("35"):
                score += Decimal("0.05")
            elif side is PositionSide.SHORT and rsi >= Decimal("55"):
                score += Decimal("0.02")
            elif side is PositionSide.LONG and rsi <= Decimal("45"):
                score += Decimal("0.02")

        # 5. Volume expansion
        if volume_sma > _DECIMAL_ZERO and volume >= volume_sma * Decimal("1.2"):
            score += Decimal("0.05")
        elif volume_sma > _DECIMAL_ZERO and volume >= volume_sma:
            score += Decimal("0.02")

        return min(_MAX_CONFIDENCE, score)

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
        """Compute composite deterministic signal confluence score (signal_score).

        Note:
            This metric is a deterministic, bounded heuristic confluence score
            combining candlestick geometry, momentum, and volume confirmations.
            It is NOT an empirical win rate probability.
        """
        score = _BASE_CONFLUENCE_SCORE

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
