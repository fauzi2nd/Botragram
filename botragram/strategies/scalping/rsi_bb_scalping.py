"""
Botragram

Description:
    Production-ready RSI and Bollinger Bands mean-reversion scalping strategy
    with dynamic ATR risk exits, trend gating, volume absorption, and ranging
    regime classification for crypto futures.

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
from botragram.indicators import (
    calculate_adx,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_rsi,
)
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "RSIBBScalpingStrategy",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Decimal = Decimal("0")
_DECIMAL_ONE: Decimal = Decimal("1")
_DECIMAL_ONE_HUNDRED: Decimal = Decimal("100")

# Confidence Scoring Weights
_DEFAULT_BASE_CONFIDENCE: Decimal = Decimal("0.60")
_DEFAULT_MAX_CONFIDENCE: Decimal = Decimal("0.95")
_DEFAULT_CONFIDENCE_BONUS: Decimal = Decimal("0.10")
_DEFAULT_SMALL_BONUS: Decimal = Decimal("0.05")

# Deep Extremity Thresholds
_DEEP_RSI_OVERSOLD: Decimal = Decimal("25.0")
_DEEP_RSI_OVERBOUGHT: Decimal = Decimal("75.0")
_LOW_ADX_QUIET_THRESHOLD: Decimal = Decimal("20.0")


# =============================================================================
# Strategy Class
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class RSIBBScalpingStrategy(BaseStrategy):
    """Generate robust mean-reversion scalping signals from RSI and Bollinger Bands."""

    # Bollinger Bands
    bb_period: int = 20
    bb_standard_deviation: Decimal = Decimal("2.0")

    # RSI
    rsi_period: int = 14
    rsi_oversold: Decimal = Decimal("30.0")
    rsi_overbought: Decimal = Decimal("70.0")

    # ATR & Dynamic Risk Exits
    atr_period: int = 14
    atr_multiplier_sl: Decimal = Decimal("1.5")
    atr_multiplier_tp: Decimal = Decimal("2.0")
    max_natr_threshold: Decimal = Decimal("0.035")

    # Regime & Anti-Trend Filter
    adx_period: int = 14
    adx_ranging_threshold: Decimal = Decimal("25.0")
    ranging_only: bool = True
    trend_filter_period: int = 50
    require_trend_filter: bool = True

    # Volume & Price Action Confirmation
    volume_period: int = 20
    min_volume_ratio: Decimal = Decimal("0.70")
    volume_climax_multiplier: Decimal = Decimal("1.50")
    min_wick_ratio: Decimal = Decimal("0.25")
    strong_wick_ratio: Decimal = Decimal("0.35")

    # Minimum Confidence Gate
    min_confidence: Decimal = Decimal("0.70")

    def __post_init__(self) -> None:
        """Validate strategy configuration parameters."""
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

        if self.atr_period <= 0:
            raise ValueError("ATR period must be positive")

        if (
            self.atr_multiplier_sl <= _DECIMAL_ZERO
            or self.atr_multiplier_tp <= _DECIMAL_ZERO
        ):
            raise ValueError("ATR multipliers must be positive")

        if self.max_natr_threshold <= _DECIMAL_ZERO:
            raise ValueError("max_natr_threshold must be positive")

        if self.adx_period <= 0 or self.adx_ranging_threshold <= _DECIMAL_ZERO:
            raise ValueError("ADX parameters must be positive")

        if self.trend_filter_period <= 0:
            raise ValueError("trend_filter_period must be positive")

        if self.volume_period <= 0 or self.min_volume_ratio <= _DECIMAL_ZERO:
            raise ValueError("Volume parameters must be positive")

        if not (_DECIMAL_ZERO <= self.min_wick_ratio <= _DECIMAL_ONE):
            raise ValueError("min_wick_ratio must be bounded between 0 and 1")

        if not (_DECIMAL_ZERO <= self.strong_wick_ratio <= _DECIMAL_ONE):
            raise ValueError("strong_wick_ratio must be bounded between 0 and 1")

        if not (_DECIMAL_ZERO <= self.min_confidence <= _DECIMAL_ONE):
            raise ValueError("min_confidence must be bounded between 0 and 1")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.RSI_BB_SCALPING

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required for base evaluation."""
        return max(self.bb_period, self.rsi_period) + 2

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a validated scalping signal with dynamic risk and regime filters."""
        self.validate_candles(candles=candles)

        close_prices = tuple(candle.close_price for candle in candles)
        high_prices = tuple(candle.high_price for candle in candles)
        low_prices = tuple(candle.low_price for candle in candles)
        volumes = tuple(candle.volume for candle in candles)

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
        current_middle_bb = bb_result.middle[-1]

        # Guard: Flat market / collapsed Bollinger Bands
        band_width = abs(current_upper_bb - current_lower_bb)
        candle_span = current_candle.high_price - current_candle.low_price
        if band_width <= _DECIMAL_ZERO or candle_span <= _DECIMAL_ZERO:
            return Signal(
                symbol=current_candle.symbol,
                signal_type=SignalType.HOLD,
                price=current_close,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=current_candle.close_time,
                reason="Flat market or zero Bollinger Band width detected",
            )

        # 1. Volatility Gate: Dynamic ATR and Extreme Shock Check
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
                    return Signal(
                        symbol=current_candle.symbol,
                        signal_type=SignalType.HOLD,
                        price=current_close,
                        confidence=_DECIMAL_ZERO,
                        strategy_name=self.strategy_type.value,
                        generated_at=current_candle.close_time,
                        reason=(
                            "Extreme volatility shock: NATR exceeds safety threshold"
                        ),
                    )

        # 2. Regime Filter: ADX Ranging-Only Gate
        current_adx = _DECIMAL_ZERO
        if len(candles) >= self.adx_period + 1:
            adx_result = calculate_adx(
                high_prices,
                low_prices,
                close_prices,
                period=self.adx_period,
            )
            if adx_result.adx:
                current_adx = adx_result.adx[-1]
                if self.ranging_only and current_adx >= self.adx_ranging_threshold:
                    return Signal(
                        symbol=current_candle.symbol,
                        signal_type=SignalType.HOLD,
                        price=current_close,
                        confidence=_DECIMAL_ZERO,
                        strategy_name=self.strategy_type.value,
                        generated_at=current_candle.close_time,
                        reason=(
                            f"Strong trend (ADX {current_adx:.1f} >= "
                            f"{self.adx_ranging_threshold:.1f}): withheld"
                        ),
                    )

        # 3. Macro Trend Alignment Gate
        trend_ok_for_long = True
        trend_ok_for_short = True
        if self.require_trend_filter and len(candles) >= self.trend_filter_period + 1:
            ema_series = calculate_ema(close_prices, period=self.trend_filter_period)
            if len(ema_series) >= 2:
                current_trend_ema = ema_series[-1]
                trend_slope_positive = current_trend_ema >= ema_series[-2]
                trend_ok_for_long = (
                    current_close >= current_trend_ema
                ) or trend_slope_positive
                trend_ok_for_short = (current_close <= current_trend_ema) or (
                    not trend_slope_positive
                )

        # 4. Price Action Rejection Wick & Volume Confirmation
        candle_span = current_candle.high_price - current_candle.low_price
        lower_wick = (
            min(current_candle.open_price, current_close) - current_candle.low_price
        )
        upper_wick = current_candle.high_price - max(
            current_candle.open_price, current_close
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
                    volume_ok = current_candle.volume >= avg_vol * self.min_volume_ratio
                    volume_climax = (
                        current_candle.volume >= avg_vol * self.volume_climax_multiplier
                    )

        # 5. Signal Evaluation
        signal_type, reason, dominant_wick_ratio = self._evaluate_scalping_setup(
            current_candle=current_candle,
            previous_candle=previous_candle,
            current_rsi=current_rsi,
            previous_rsi=previous_rsi,
            current_lower_bb=current_lower_bb,
            previous_lower_bb=previous_lower_bb,
            current_upper_bb=current_upper_bb,
            previous_upper_bb=previous_upper_bb,
            current_middle_bb=current_middle_bb,
            current_atr=current_atr,
            trend_ok_for_long=trend_ok_for_long,
            trend_ok_for_short=trend_ok_for_short,
            volume_ok=volume_ok,
            lower_wick_ratio=lower_wick_ratio,
            upper_wick_ratio=upper_wick_ratio,
        )

        # 6. Advanced Confidence Scoring
        confidence = self._compute_confidence(
            signal_type=signal_type,
            current_rsi=current_rsi,
            dominant_wick_ratio=dominant_wick_ratio,
            volume_climax=volume_climax,
            current_adx=current_adx,
        )

        # 7. Minimum Confidence Gate
        if signal_type is not SignalType.HOLD and confidence < self.min_confidence:
            return Signal(
                symbol=current_candle.symbol,
                signal_type=SignalType.HOLD,
                price=current_close,
                confidence=confidence,
                strategy_name=self.strategy_type.value,
                generated_at=current_candle.close_time,
                reason=(
                    f"RSI/BB signal withheld: confidence ({confidence:.2f}) < "
                    f"minimum threshold ({self.min_confidence:.2f})"
                ),
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

    def _evaluate_scalping_setup(
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
        trend_ok_for_long: bool,
        trend_ok_for_short: bool,
        volume_ok: bool,
        lower_wick_ratio: Decimal,
        upper_wick_ratio: Decimal,
    ) -> tuple[SignalType, str, Decimal]:
        """Evaluate entry conditions for Long/Short mean-reversion scalping."""
        # BUY (Long): Oversold bounce at or below lower Bollinger Band
        is_oversold_touch = (
            previous_candle.low_price <= previous_lower_bb
            or current_candle.low_price <= current_lower_bb
        )
        is_rsi_oversold_turning = (
            previous_rsi <= self.rsi_oversold or current_rsi <= self.rsi_oversold
        ) and current_rsi >= previous_rsi
        is_bullish_rejection = (
            lower_wick_ratio >= self.min_wick_ratio
            or current_candle.close_price > current_candle.open_price
        )

        if is_oversold_touch and is_rsi_oversold_turning and is_bullish_rejection:
            if not volume_ok:
                return (
                    SignalType.HOLD,
                    "RSI oversold bounce rejected: insufficient volume confirmation",
                    lower_wick_ratio,
                )
            if not trend_ok_for_long:
                return (
                    SignalType.HOLD,
                    "RSI oversold bounce rejected: counter to macro trend slope",
                    lower_wick_ratio,
                )

            sl_dist = (
                current_atr * self.atr_multiplier_sl
                if current_atr > _DECIMAL_ZERO
                else current_candle.close_price * Decimal("0.015")
            )
            tp_dist = (
                current_atr * self.atr_multiplier_tp
                if current_atr > _DECIMAL_ZERO
                else current_candle.close_price * Decimal("0.020")
            )
            reason = (
                f"RSI oversold bounce off lower BB (RSI {current_rsi:.1f}, "
                f"TP1 Mid-BB: {current_middle_bb:.2f}, DynATR TP: +{tp_dist:.2f}, "
                f"DynATR SL: -{sl_dist:.2f})"
            )
            return SignalType.BUY, reason, lower_wick_ratio

        # SELL (Short): Overbought rejection at or above upper Bollinger Band
        is_overbought_touch = (
            previous_candle.high_price >= previous_upper_bb
            or current_candle.high_price >= current_upper_bb
        )
        is_rsi_overbought_turning = (
            previous_rsi >= self.rsi_overbought or current_rsi >= self.rsi_overbought
        ) and current_rsi <= previous_rsi
        is_bearish_rejection = (
            upper_wick_ratio >= self.min_wick_ratio
            or current_candle.close_price < current_candle.open_price
        )

        if is_overbought_touch and is_rsi_overbought_turning and is_bearish_rejection:
            if not volume_ok:
                return (
                    SignalType.HOLD,
                    "RSI overbought rejection withheld: insufficient volume",
                    upper_wick_ratio,
                )
            if not trend_ok_for_short:
                return (
                    SignalType.HOLD,
                    "RSI overbought rejection withheld: counter to macro trend slope",
                    upper_wick_ratio,
                )

            sl_dist = (
                current_atr * self.atr_multiplier_sl
                if current_atr > _DECIMAL_ZERO
                else current_candle.close_price * Decimal("0.015")
            )
            tp_dist = (
                current_atr * self.atr_multiplier_tp
                if current_atr > _DECIMAL_ZERO
                else current_candle.close_price * Decimal("0.020")
            )
            reason = (
                f"RSI overbought rejection off upper BB (RSI {current_rsi:.1f}, "
                f"TP1 Mid-BB: {current_middle_bb:.2f}, DynATR TP: -{tp_dist:.2f}, "
                f"DynATR SL: +{sl_dist:.2f})"
            )
            return SignalType.SELL, reason, upper_wick_ratio

        return SignalType.HOLD, "No RSI/BB scalping setup triggered", _DECIMAL_ZERO

    def _compute_confidence(
        self,
        *,
        signal_type: SignalType,
        current_rsi: Decimal,
        dominant_wick_ratio: Decimal,
        volume_climax: bool,
        current_adx: Decimal,
    ) -> Decimal:
        """Calculate bounded, multi-confluence confidence score."""
        if signal_type is SignalType.HOLD:
            return _DECIMAL_ZERO

        confidence = _DEFAULT_BASE_CONFIDENCE

        # 1. Price action rejection wick quality
        if dominant_wick_ratio >= self.strong_wick_ratio:
            confidence += _DEFAULT_CONFIDENCE_BONUS
        elif dominant_wick_ratio >= self.min_wick_ratio:
            confidence += _DEFAULT_SMALL_BONUS

        # 2. Deep RSI extremity confirmation
        if signal_type is SignalType.BUY and current_rsi <= _DEEP_RSI_OVERSOLD:
            confidence += _DEFAULT_CONFIDENCE_BONUS
        elif signal_type is SignalType.SELL and current_rsi >= _DEEP_RSI_OVERBOUGHT:
            confidence += _DEFAULT_CONFIDENCE_BONUS

        # 3. Volume absorption / climax bonus
        if volume_climax:
            confidence += _DEFAULT_CONFIDENCE_BONUS

        # 4. Pure ranging market bonus
        if _DECIMAL_ZERO < current_adx < _LOW_ADX_QUIET_THRESHOLD:
            confidence += _DEFAULT_SMALL_BONUS

        return min(max(confidence, _DEFAULT_BASE_CONFIDENCE), _DEFAULT_MAX_CONFIDENCE)
