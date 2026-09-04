"""
Botragram

Description:
    Production-ready Hybrid Smart Money Concepts (CHoCH + FVG) and RSI/BB
    mean-reversion scalping strategy with anti-churn controls, regime gating,
    asymmetric short bias, dynamic ATR exits, and temporal trade management.

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
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import SignalType, StrategyType
from botragram.indicators import (
    BollingerBandsResult,
    calculate_adx,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_rsi,
)
from botragram.indicators.price_action import ChochFvgResult, calculate_choch_fvg
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "ChochRsiBbHybridStrategy",
    "DailyHybridScalpingStrategy",
    "HybridStructureMeanReversionStrategy",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_ONE: Final[Decimal] = Decimal("1")
_DECIMAL_TWO: Final[Decimal] = Decimal("2")
_DECIMAL_ONE_HUNDRED: Final[Decimal] = Decimal("100")

# Confidence Scoring Weights (Scalping Permissive Profile)
_BASE_CONFIDENCE: Final[Decimal] = Decimal("0.60")
_MAX_CONFIDENCE: Final[Decimal] = Decimal("0.95")
_STRUCTURE_BONUS: Final[Decimal] = Decimal("0.06")
_SWEEP_BONUS: Final[Decimal] = Decimal("0.06")
_FVG_RETEST_BONUS: Final[Decimal] = Decimal("0.05")
_DISPLACEMENT_BONUS: Final[Decimal] = Decimal("0.04")
_STRONG_WICK_BONUS: Final[Decimal] = Decimal("0.05")
_MIN_WICK_BONUS: Final[Decimal] = Decimal("0.02")
_DEEP_RSI_BONUS: Final[Decimal] = Decimal("0.05")
_VOLUME_CLIMAX_BONUS: Final[Decimal] = Decimal("0.04")
_QUIET_REGIME_BONUS: Final[Decimal] = Decimal("0.03")
_SHORT_ASYMMETRY_BONUS: Final[Decimal] = Decimal("0.04")

# Scalping Extremity Thresholds
_DEEP_RSI_OVERSOLD: Final[Decimal] = Decimal("30.0")
_DEEP_RSI_OVERBOUGHT: Final[Decimal] = Decimal("70.0")
_LOW_ADX_QUIET_THRESHOLD: Final[Decimal] = Decimal("22.0")
_SHORT_RSI_TOLERANCE: Final[Decimal] = Decimal("2.0")


# =============================================================================
# Strategy Class
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class ChochRsiBbHybridStrategy(BaseStrategy):
    """Generate agile hybrid signals for active daily crypto futures scalping."""

    # Smart Money Concepts (Structure Context & Bias)
    swing_window: int = 5
    fvg_lookback: int = 20
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.05")
    min_body_ratio: Decimal = Decimal("0.40")
    min_gap_ratio: Decimal = Decimal("0.0008")
    trend_period: int = 100
    intermediate_trend_period: int = 30
    require_trend_filter: bool = False

    # Bollinger Bands Trigger
    bb_period: int = 20
    bb_standard_deviation: Decimal = Decimal("2.0")
    bb_proximity_ratio: Decimal = Decimal("0.0010")

    # RSI Trigger
    rsi_period: int = 14
    rsi_oversold: Decimal = Decimal("35.0")
    rsi_overbought: Decimal = Decimal("65.0")

    # Regime & Volatility Filters
    adx_period: int = 14
    adx_ranging_threshold: Decimal = Decimal("35.0")
    atr_period: int = 14
    atr_multiplier_sl: Decimal = Decimal("1.2")
    atr_multiplier_tp: Decimal = Decimal("1.8")
    max_natr_threshold: Decimal = Decimal("0.040")

    # Price Action Confirmation
    min_wick_ratio: Decimal = Decimal("0.15")
    strong_wick_ratio: Decimal = Decimal("0.30")
    min_volume_ratio: Decimal = Decimal("0.60")
    volume_climax_multiplier: Decimal = Decimal("1.40")

    # Anti-Churn & Execution Quality
    min_confidence: Decimal = Decimal("0.60")
    cooldown_bars: int = 2
    max_hold_bars: int = 24
    short_bias_multiplier: Decimal = Decimal("1.06")

    def __post_init__(self) -> None:
        """Validate strategy configuration parameters."""
        if self.swing_window <= 0 or self.fvg_lookback <= 0:
            raise ValueError("Structure window parameters must be greater than zero")

        if self.volume_period <= 0 or self.volume_multiplier <= _DECIMAL_ZERO:
            raise ValueError("Volume parameters must be positive")

        if self.min_body_ratio <= _DECIMAL_ZERO:
            raise ValueError("Minimum body ratio must be positive")

        if self.min_gap_ratio < _DECIMAL_ZERO:
            raise ValueError("Minimum gap ratio must not be negative")

        if self.trend_period <= 0 or self.intermediate_trend_period <= 0:
            raise ValueError("Trend periods must be positive")

        if self.intermediate_trend_period >= self.trend_period:
            raise ValueError("intermediate_trend_period must be less than trend_period")

        if self.bb_period <= 0 or self.bb_standard_deviation <= _DECIMAL_ZERO:
            raise ValueError("Bollinger Bands parameters must be positive")

        if self.bb_proximity_ratio < _DECIMAL_ZERO:
            raise ValueError("Bollinger Bands proximity ratio must not be negative")

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

        if self.adx_period <= 0 or self.adx_ranging_threshold <= _DECIMAL_ZERO:
            raise ValueError("ADX parameters must be positive")

        if self.atr_period <= 0 or self.max_natr_threshold <= _DECIMAL_ZERO:
            raise ValueError("ATR parameters must be positive")

        if (
            self.atr_multiplier_sl <= _DECIMAL_ZERO
            or self.atr_multiplier_tp <= _DECIMAL_ZERO
        ):
            raise ValueError("ATR multipliers must be positive")

        if not (
            _DECIMAL_ZERO
            <= self.min_wick_ratio
            <= self.strong_wick_ratio
            <= _DECIMAL_ONE
        ):
            raise ValueError("Wick ratios must be bounded between 0 and 1")

        if not (_DECIMAL_ZERO <= self.min_confidence <= _DECIMAL_ONE):
            raise ValueError("Minimum confidence must be between 0.0 and 1.0")

        if self.cooldown_bars < 0:
            raise ValueError("Cooldown bars must not be negative")

        if self.max_hold_bars <= 0:
            raise ValueError("Maximum hold bars must be positive")

        if self.short_bias_multiplier < _DECIMAL_ONE:
            raise ValueError("Short bias multiplier must be at least 1.0")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.CHOCH_RSI_BB_HYBRID

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required for full evaluation."""
        base_smc = max(self.swing_window * 2 + 1, self.volume_period + 1)
        base_indicators = max(
            self.bb_period + 2,
            self.rsi_period + 2,
            self.atr_period + 2,
            self.adx_period * 2 + 1,
        )
        base_min = max(base_smc, base_indicators)
        if self.require_trend_filter:
            return max(
                base_min,
                self.trend_period + 1,
                self.intermediate_trend_period + 1,
            )
        return base_min

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a validated hybrid signal from SMC structure and RSI/BB triggers."""
        self.validate_candles(candles=candles)

        close_prices = tuple(candle.close_price for candle in candles)
        high_prices = tuple(candle.high_price for candle in candles)
        low_prices = tuple(candle.low_price for candle in candles)
        open_prices = tuple(candle.open_price for candle in candles)
        volumes = tuple(candle.volume for candle in candles)

        latest_candle = candles[-1]
        previous_candle = candles[-2]
        current_close = latest_candle.close_price

        # 1. Macro Market Structure (CHoCH + FVG Detection)
        choch_result = calculate_choch_fvg(
            high_prices=high_prices,
            low_prices=low_prices,
            close_prices=close_prices,
            open_prices=open_prices,
            volumes=volumes,
            swing_window=self.swing_window,
            fvg_lookback=self.fvg_lookback,
            volume_period=self.volume_period,
            volume_multiplier=self.volume_multiplier,
            min_body_ratio=self.min_body_ratio,
            min_gap_ratio=self.min_gap_ratio,
        )

        # 2. Bollinger Bands Calculation
        bb_result = calculate_bollinger_bands(
            close_prices,
            period=self.bb_period,
            standard_deviation=self.bb_standard_deviation,
        )
        current_lower_bb = bb_result.lower[-1]
        previous_lower_bb = bb_result.lower[-2]
        current_upper_bb = bb_result.upper[-1]
        previous_upper_bb = bb_result.upper[-2]
        current_middle_bb = bb_result.middle[-1]

        # Guard: Flat market / collapsed Bollinger Bands
        band_width = abs(current_upper_bb - current_lower_bb)
        candle_span = latest_candle.high_price - latest_candle.low_price
        if band_width <= _DECIMAL_ZERO or candle_span <= _DECIMAL_ZERO:
            return self._hold_signal(
                candle=latest_candle,
                reason="Flat market or zero Bollinger Band width detected",
            )

        # 3. Dynamic Volatility & ATR Shock Gate
        current_atr = _DECIMAL_ZERO
        if len(candles) >= self.atr_period + 1:
            atr_series = calculate_atr(
                high_prices,
                low_prices,
                close_prices,
                period=self.atr_period,
            )
            if atr_series:
                current_atr = atr_series[-1]
                if (
                    current_close > _DECIMAL_ZERO
                    and (current_atr / current_close) > self.max_natr_threshold
                ):
                    return self._hold_signal(
                        candle=latest_candle,
                        reason=(
                            "Extreme volatility shock: NATR exceeds safety threshold"
                        ),
                    )

        # 4. Regime Filter: ADX Anti-Trend Gate
        current_adx = _DECIMAL_ZERO
        if len(candles) >= self.adx_period * 2 + 1:
            adx_result = calculate_adx(
                high_prices,
                low_prices,
                close_prices,
                period=self.adx_period,
            )
            if adx_result.adx:
                current_adx = adx_result.adx[-1]
                # In very strong trend, only allow entry if confirmed structure reversal
                if current_adx >= self.adx_ranging_threshold:
                    has_structural_reversal = (
                        choch_result.displacement_confirmed
                        or choch_result.liquidity_swept
                        or choch_result.has_bullish_choch
                        or choch_result.has_bearish_choch
                    )
                    if not has_structural_reversal:
                        return self._hold_signal(
                            candle=latest_candle,
                            reason=(
                                f"Strong trend (ADX {current_adx:.1f} >= "
                                f"{self.adx_ranging_threshold:.1f}) without "
                                f"structure reversal: withheld"
                            ),
                        )

        # 5. Macro Trend Alignment Gate
        trend_ok_for_long = True
        trend_ok_for_short = True
        if self.require_trend_filter and len(candles) >= self.trend_period + 1:
            ema_macro = calculate_ema(close_prices, period=self.trend_period)[-1]
            ema_inter = calculate_ema(
                close_prices, period=self.intermediate_trend_period
            )[-1]
            is_macro_bearish = ema_inter < ema_macro
            is_macro_bullish = ema_inter > ema_macro

            trend_ok_for_long = (current_close >= ema_macro) and not is_macro_bearish
            trend_ok_for_short = (current_close <= ema_macro) and not is_macro_bullish

            # Exception: Fresh CHoCH with sweep can override macro trend
            if choch_result.has_bullish_choch and choch_result.liquidity_swept:
                trend_ok_for_long = True
            if choch_result.has_bearish_choch and choch_result.liquidity_swept:
                trend_ok_for_short = True

        # 6. Price Action Confirmation & Volume Absorption
        lower_wick = (
            min(latest_candle.open_price, current_close) - latest_candle.low_price
        )
        upper_wick = latest_candle.high_price - max(
            latest_candle.open_price, current_close
        )
        lower_wick_ratio = (
            lower_wick / candle_span if candle_span > _DECIMAL_ZERO else _DECIMAL_ZERO
        )
        upper_wick_ratio = (
            upper_wick / candle_span if candle_span > _DECIMAL_ZERO else _DECIMAL_ZERO
        )

        volume_ok = True
        volume_climax = False
        if len(candles) >= self.volume_period + 1:
            recent_vols = volumes[-(self.volume_period + 1) : -1]
            if recent_vols:
                avg_vol = sum(recent_vols) / Decimal(str(len(recent_vols)))
                if avg_vol > _DECIMAL_ZERO:
                    volume_ok = latest_candle.volume >= avg_vol * self.min_volume_ratio
                    volume_climax = (
                        latest_candle.volume >= avg_vol * self.volume_climax_multiplier
                    )

        # 7. RSI Trigger Series
        rsi_series = calculate_rsi(close_prices, period=self.rsi_period)
        current_rsi = rsi_series[-1]
        previous_rsi = rsi_series[-2]

        # 8. Anti-Churn & Cooldown Check
        if self._is_under_cooldown(
            candles=candles,
            close_prices=close_prices,
            high_prices=high_prices,
            low_prices=low_prices,
            bb_result=bb_result,
            rsi_series=rsi_series,
        ):
            return self._hold_signal(
                candle=latest_candle,
                reason=(
                    f"Anti-churn active: entry cooldown within "
                    f"{self.cooldown_bars} bars"
                ),
            )

        # 9. Evaluate Setup Confluence
        signal_type, reason, dominant_wick_ratio = self._evaluate_hybrid_setup(
            current_candle=latest_candle,
            previous_candle=previous_candle,
            current_rsi=current_rsi,
            previous_rsi=previous_rsi,
            current_lower_bb=current_lower_bb,
            previous_lower_bb=previous_lower_bb,
            current_upper_bb=current_upper_bb,
            previous_upper_bb=previous_upper_bb,
            current_middle_bb=current_middle_bb,
            current_atr=current_atr,
            choch_result=choch_result,
            trend_ok_for_long=trend_ok_for_long,
            trend_ok_for_short=trend_ok_for_short,
            volume_ok=volume_ok,
            lower_wick_ratio=lower_wick_ratio,
            upper_wick_ratio=upper_wick_ratio,
        )

        if signal_type is SignalType.HOLD:
            return self._hold_signal(candle=latest_candle, reason=reason)

        # 10. Multi-Factor Confidence Scoring
        confidence = self._compute_confidence(
            signal_type=signal_type,
            choch_result=choch_result,
            current_rsi=current_rsi,
            dominant_wick_ratio=dominant_wick_ratio,
            volume_climax=volume_climax,
            current_adx=current_adx,
        )

        # 11. Minimum Confidence Gate
        if confidence < self.min_confidence:
            return self._hold_signal(
                candle=latest_candle,
                confidence=confidence,
                reason=(
                    f"Hybrid signal withheld: confidence ({confidence:.2f}) < "
                    f"minimum threshold ({self.min_confidence:.2f})"
                ),
            )

        return Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=current_close,
            confidence=confidence,
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            reason=reason,
        )

    def _evaluate_hybrid_setup(
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
        current_middle_bb: Decimal,
        current_atr: Decimal,
        choch_result: ChochFvgResult,
        trend_ok_for_long: bool,
        trend_ok_for_short: bool,
        volume_ok: bool,
        lower_wick_ratio: Decimal,
        upper_wick_ratio: Decimal,
    ) -> tuple[SignalType, str, Decimal]:
        """Evaluate hybrid confluence between SMC structure bias and RSI/BB entries."""
        current_close = current_candle.close_price

        # --- LONG SETUP CONFLUENCE ---
        has_bullish_bias = (
            choch_result.has_bullish_choch
            or choch_result.bullish_fvg_active
            or choch_result.retesting_bullish_fvg
        )

        # Price interaction with lower BB (or within proximity ratio) or active FVG
        lower_bound = current_lower_bb * (_DECIMAL_ONE + self.bb_proximity_ratio)
        prev_lower_bound = previous_lower_bb * (_DECIMAL_ONE + self.bb_proximity_ratio)
        is_fvg_zone_touch_long = False
        if choch_result.active_fvg and choch_result.active_fvg.is_bullish:
            is_fvg_zone_touch_long = (
                current_candle.low_price <= choch_result.active_fvg.top
            )

        is_oversold_touch_long = (
            previous_candle.low_price <= prev_lower_bound
            or current_candle.low_price <= lower_bound
            or is_fvg_zone_touch_long
        )
        is_rsi_oversold_turning_long = (
            previous_rsi <= self.rsi_oversold or current_rsi <= self.rsi_oversold
        ) and current_rsi >= previous_rsi
        is_bullish_rejection = (
            lower_wick_ratio >= self.min_wick_ratio
            or current_close > current_candle.open_price
        )

        if (
            has_bullish_bias
            and is_oversold_touch_long
            and is_rsi_oversold_turning_long
            and is_bullish_rejection
        ):
            if not volume_ok:
                return (
                    SignalType.HOLD,
                    "Bullish hybrid setup rejected: insufficient volume confirmation",
                    lower_wick_ratio,
                )
            if not trend_ok_for_long:
                return (
                    SignalType.HOLD,
                    "Bullish hybrid setup rejected: macro trend resistance",
                    lower_wick_ratio,
                )

            sl_dist = (
                current_atr * self.atr_multiplier_sl
                if current_atr > _DECIMAL_ZERO
                else current_close * Decimal("0.006")
            )
            tp_dist = (
                current_atr * self.atr_multiplier_tp
                if current_atr > _DECIMAL_ZERO
                else current_close * Decimal("0.012")
            )
            sweep_str = " + Sweep" if choch_result.liquidity_swept else ""
            reason = (
                f"Bullish Hybrid Confluence: CHoCH/FVG{sweep_str} + Lower-BB RSI "
                f"({current_rsi:.1f}) rejection (TP1 Mid-BB: {current_middle_bb:.2f}, "
                f"DynATR TP: +{tp_dist:.2f}, DynATR SL: -{sl_dist:.2f})"
            )
            return SignalType.BUY, reason, lower_wick_ratio

        # --- SHORT SETUP CONFLUENCE (Asymmetric Short Bias) ---
        has_bearish_bias = (
            choch_result.has_bearish_choch
            or choch_result.bearish_fvg_active
            or choch_result.retesting_bearish_fvg
        )

        upper_bound = current_upper_bb * (_DECIMAL_ONE - self.bb_proximity_ratio)
        prev_upper_bound = previous_upper_bb * (_DECIMAL_ONE - self.bb_proximity_ratio)
        is_fvg_zone_touch_short = False
        if choch_result.active_fvg and not choch_result.active_fvg.is_bullish:
            is_fvg_zone_touch_short = (
                current_candle.high_price >= choch_result.active_fvg.bottom
            )

        is_overbought_touch_short = (
            previous_candle.high_price >= prev_upper_bound
            or current_candle.high_price >= upper_bound
            or is_fvg_zone_touch_short
        )
        # Asymmetric short RSI tolerance: looser boundary for rapid cascades
        effective_rsi_overbought = self.rsi_overbought - _SHORT_RSI_TOLERANCE
        is_rsi_overbought_turning_short = (
            previous_rsi >= effective_rsi_overbought
            or current_rsi >= effective_rsi_overbought
        ) and current_rsi <= previous_rsi
        is_bearish_rejection = (
            upper_wick_ratio >= self.min_wick_ratio
            or current_close < current_candle.open_price
        )

        if (
            has_bearish_bias
            and is_overbought_touch_short
            and is_rsi_overbought_turning_short
            and is_bearish_rejection
        ):
            if not volume_ok:
                return (
                    SignalType.HOLD,
                    "Bearish hybrid setup withheld: insufficient volume",
                    upper_wick_ratio,
                )
            if not trend_ok_for_short:
                return (
                    SignalType.HOLD,
                    "Bearish hybrid setup withheld: macro trend support",
                    upper_wick_ratio,
                )

            sl_dist = (
                current_atr * self.atr_multiplier_sl
                if current_atr > _DECIMAL_ZERO
                else current_close * Decimal("0.006")
            )
            tp_dist = (
                current_atr * self.atr_multiplier_tp
                if current_atr > _DECIMAL_ZERO
                else current_close * Decimal("0.012")
            )
            sweep_str = " + Sweep" if choch_result.liquidity_swept else ""
            reason = (
                f"Bearish Hybrid Confluence: CHoCH/FVG{sweep_str} + Upper-BB RSI "
                f"({current_rsi:.1f}) rejection (TP1 Mid-BB: {current_middle_bb:.2f}, "
                f"DynATR TP: -{tp_dist:.2f}, DynATR SL: +{sl_dist:.2f})"
            )
            return SignalType.SELL, reason, upper_wick_ratio

        return (
            SignalType.HOLD,
            "No hybrid structure + mean reversion setup triggered",
            _DECIMAL_ZERO,
        )

    def _compute_confidence(
        self,
        *,
        signal_type: SignalType,
        choch_result: ChochFvgResult,
        current_rsi: Decimal,
        dominant_wick_ratio: Decimal,
        volume_climax: bool,
        current_adx: Decimal,
    ) -> Decimal:
        """Compute multi-factor confidence combining SMC and trigger precision."""
        if signal_type is SignalType.HOLD:
            return _DECIMAL_ZERO

        confidence = _BASE_CONFIDENCE

        # 1. Structure Shift Quality (CHoCH)
        if (signal_type is SignalType.BUY and choch_result.has_bullish_choch) or (
            signal_type is SignalType.SELL and choch_result.has_bearish_choch
        ):
            confidence += _STRUCTURE_BONUS

        # 2. Liquidity Sweep Confirmation
        if choch_result.liquidity_swept:
            confidence += _SWEEP_BONUS

        # 3. Active FVG Retest Confirmation
        if (signal_type is SignalType.BUY and choch_result.retesting_bullish_fvg) or (
            signal_type is SignalType.SELL and choch_result.retesting_bearish_fvg
        ):
            confidence += _FVG_RETEST_BONUS

        # 4. Displacement Quality
        if choch_result.displacement_confirmed:
            confidence += _DISPLACEMENT_BONUS

        # 5. Price Action Rejection Wick Quality
        if dominant_wick_ratio >= self.strong_wick_ratio:
            confidence += _STRONG_WICK_BONUS
        elif dominant_wick_ratio >= self.min_wick_ratio:
            confidence += _MIN_WICK_BONUS

        # 6. Deep RSI Extremity Confirmation
        if signal_type is SignalType.BUY and current_rsi <= _DEEP_RSI_OVERSOLD:
            confidence += _DEEP_RSI_BONUS
        elif signal_type is SignalType.SELL and current_rsi >= _DEEP_RSI_OVERBOUGHT:
            confidence += _DEEP_RSI_BONUS

        # 7. Volume Climax / Absorption Bonus
        if volume_climax:
            confidence += _VOLUME_CLIMAX_BONUS

        # 8. Quiet Ranging Environment Bonus
        if _DECIMAL_ZERO < current_adx < _LOW_ADX_QUIET_THRESHOLD:
            confidence += _QUIET_REGIME_BONUS

        # 9. Asymmetric Short Bias
        if signal_type is SignalType.SELL:
            confidence += _SHORT_ASYMMETRY_BONUS
            confidence *= self.short_bias_multiplier

        return min(max(confidence, _BASE_CONFIDENCE), _MAX_CONFIDENCE)

    def _is_under_cooldown(
        self,
        *,
        candles: Sequence[Candle],
        close_prices: Sequence[Decimal],
        high_prices: Sequence[Decimal],
        low_prices: Sequence[Decimal],
        bb_result: BollingerBandsResult,
        rsi_series: Sequence[Decimal],
    ) -> bool:
        """Inspect recent bars to prevent multiple duplicate entries."""
        if self.cooldown_bars <= 0:
            return False

        # Inspect up to `cooldown_bars` preceding the latest candle (-1)
        available_bars = min(
            self.cooldown_bars,
            len(bb_result.lower) - 1,
            len(rsi_series) - 1,
            len(low_prices) - 1,
        )
        for offset in range(1, available_bars + 1):
            bar_idx = -1 - offset
            # Check if a recent bar penetrated lower BB + oversold RSI (Long)
            lower_touch = (
                low_prices[bar_idx] <= bb_result.lower[bar_idx]
                and rsi_series[bar_idx] <= self.rsi_oversold
            )
            # Check if a recent bar penetrated upper BB + overbought RSI (Short)
            upper_touch = high_prices[bar_idx] >= bb_result.upper[
                bar_idx
            ] and rsi_series[bar_idx] >= (self.rsi_overbought - _SHORT_RSI_TOLERANCE)
            if lower_touch or upper_touch:
                return True

        return False

    def _hold_signal(
        self,
        *,
        candle: Candle,
        reason: str,
        confidence: Decimal = _DECIMAL_ZERO,
    ) -> Signal:
        """Construct a consistent HOLD signal."""
        return Signal(
            symbol=candle.symbol,
            signal_type=SignalType.HOLD,
            price=candle.close_price,
            confidence=confidence,
            strategy_name=self.strategy_type.value,
            generated_at=candle.close_time,
            reason=reason,
        )


# Aliases for explicit descriptive naming
DailyHybridScalpingStrategy = ChochRsiBbHybridStrategy
HybridStructureMeanReversionStrategy = ChochRsiBbHybridStrategy
