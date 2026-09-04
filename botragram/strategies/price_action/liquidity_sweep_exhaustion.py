"""
Botragram

Description:
    Liquidity Sweep Exhaustion (LSE) daily scalping strategy.

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
from datetime import timezone
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import SignalType, StrategyType
from botragram.indicators import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_rsi,
)
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = ["LiquiditySweepExhaustionStrategy"]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_ONE: Final[Decimal] = Decimal("1")
_DECIMAL_TWO: Final[Decimal] = Decimal("2")
_DECIMAL_ONE_HUNDRED: Final[Decimal] = Decimal("100")

# Confidence Scoring Constants
_BASE_CONFIDENCE: Final[Decimal] = Decimal("0.60")
_MAX_CONFIDENCE: Final[Decimal] = Decimal("0.95")
_STRONG_WICK_BONUS: Final[Decimal] = Decimal("0.06")
_VOLUME_SURGE_BONUS: Final[Decimal] = Decimal("0.06")
_DEEP_RSI_BONUS: Final[Decimal] = Decimal("0.05")
_STRONG_CONFIRMATION_BONUS: Final[Decimal] = Decimal("0.05")
_SHORT_ASYMMETRY_BONUS: Final[Decimal] = Decimal("0.04")

# Threshold Constants
_STRONG_WICK_THRESHOLD: Final[Decimal] = Decimal("0.60")
_VOLUME_SURGE_THRESHOLD: Final[Decimal] = Decimal("1.80")
_DEEP_RSI_OVERSOLD: Final[Decimal] = Decimal("30.0")
_DEEP_RSI_OVERBOUGHT: Final[Decimal] = Decimal("70.0")
_SHORT_RSI_TOLERANCE: Final[Decimal] = Decimal("2.0")
_SHORT_VOLUME_TOLERANCE: Final[Decimal] = Decimal("0.05")
_FUNDING_HOURS: Final[frozenset[int]] = frozenset({0, 8, 16})


# =============================================================================
# Strategy Class
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class LiquiditySweepExhaustionStrategy(BaseStrategy):
    """Capture mean-reversion impulses following liquidity sweeps and exhaustion."""

    # Swing Reference Window
    swing_lookback: int = 15

    # Sweep & Exhaustion Triggers
    min_wick_ratio: Decimal = Decimal("0.50")
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.30")
    rsi_period: int = 14
    rsi_oversold: Decimal = Decimal("38.0")
    rsi_overbought: Decimal = Decimal("62.0")

    # Regime & Volatility Filters
    atr_period: int = 14
    atr_multiplier_sl: Decimal = Decimal("1.2")
    atr_multiplier_tp1: Decimal = Decimal("1.2")
    atr_multiplier_tp2: Decimal = Decimal("2.0")
    min_natr_threshold: Decimal = Decimal("0.0020")
    max_natr_threshold: Decimal = Decimal("0.0350")

    # Funding Settlement Avoidance
    filter_funding: bool = True
    funding_buffer_minutes: int = 15

    # Execution Quality & Anti-Churn
    min_confidence: Decimal = Decimal("0.60")
    cooldown_bars: int = 2
    max_hold_bars: int = 24
    short_bias_multiplier: Decimal = Decimal("1.06")

    def __post_init__(self) -> None:
        """Validate strategy configuration parameters."""
        if self.swing_lookback <= 0:
            raise ValueError("Swing lookback must be positive")
        if not (_DECIMAL_ZERO < self.min_wick_ratio <= _DECIMAL_ONE):
            raise ValueError("Minimum wick ratio must be between 0 and 1")
        if self.volume_period <= 0 or self.volume_multiplier <= _DECIMAL_ZERO:
            raise ValueError("Volume parameters must be positive")
        if self.rsi_period <= 0:
            raise ValueError("RSI period must be positive")
        if not (
            _DECIMAL_ZERO
            <= self.rsi_oversold
            < self.rsi_overbought
            <= _DECIMAL_ONE_HUNDRED
        ):
            raise ValueError("RSI oversold/overbought must be bounded within [0, 100]")
        if self.atr_period <= 0:
            raise ValueError("ATR period must be positive")
        if (
            self.atr_multiplier_sl <= _DECIMAL_ZERO
            or self.atr_multiplier_tp1 <= _DECIMAL_ZERO
            or self.atr_multiplier_tp2 <= _DECIMAL_ZERO
        ):
            raise ValueError("ATR multipliers must be positive")
        if not (_DECIMAL_ZERO <= self.min_natr_threshold < self.max_natr_threshold):
            raise ValueError("NATR thresholds must be positive and ordered")
        if self.funding_buffer_minutes < 0:
            raise ValueError("Funding buffer minutes must not be negative")
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
        return StrategyType.LIQUIDITY_SWEEP_EXHAUSTION

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required for evaluation."""
        return max(
            self.swing_lookback + 3,
            self.volume_period + 2,
            self.rsi_period + 2,
            self.atr_period + 2,
        )

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        """Evaluate market price action for liquidity sweep exhaustion setups."""
        self.validate_candles(candles=candles)

        latest_candle = candles[-1]
        sweep_candle = candles[-2]
        close_prices = tuple(c.close_price for c in candles)
        high_prices = tuple(c.high_price for c in candles)
        low_prices = tuple(c.low_price for c in candles)
        volumes = tuple(c.volume for c in candles)

        # 1. Funding Settlement Window Filter
        if self.filter_funding and self._is_in_funding_settlement_window(latest_candle):
            return self._hold_signal(
                candle=latest_candle,
                reason="Funding settlement window avoidance: withheld",
            )

        # 2. Volatility Range Filter (Normalized ATR)
        atr_series = calculate_atr(
            highs=high_prices,
            lows=low_prices,
            closes=close_prices,
            period=self.atr_period,
        )
        current_atr = atr_series[-1] if atr_series else _DECIMAL_ZERO
        if latest_candle.close_price > _DECIMAL_ZERO:
            natr = current_atr / latest_candle.close_price
            if natr < self.min_natr_threshold:
                return self._hold_signal(
                    candle=latest_candle,
                    reason=f"Volatility too low (NATR {natr:.4f}): flat market",
                )
            if natr >= self.max_natr_threshold:
                return self._hold_signal(
                    candle=latest_candle,
                    reason=f"Extreme volatility shock (NATR {natr:.4f}): withheld",
                )

        # 3. Anti-Churn Cooldown Guard
        if self._is_under_cooldown(
            candles=candles,
            high_prices=high_prices,
            low_prices=low_prices,
            volumes=volumes,
        ):
            return self._hold_signal(
                candle=latest_candle,
                reason=f"Anti-churn: zone in cooldown ({self.cooldown_bars} bars)",
            )

        # 4. Indicators & Volume Context
        rsi_series = calculate_rsi(close_prices, period=self.rsi_period)
        sweep_rsi = rsi_series[-2]
        current_rsi = rsi_series[-1]

        recent_vols = volumes[-(self.volume_period + 2) : -2]
        if not recent_vols:
            return self._hold_signal(
                candle=latest_candle, reason="Insufficient volume history"
            )
        avg_vol = sum(recent_vols) / Decimal(str(len(recent_vols)))
        if avg_vol <= _DECIMAL_ZERO:
            return self._hold_signal(candle=latest_candle, reason="Zero average volume")

        # 5. Prior Swing Reference Levels
        prior_highs = high_prices[-(self.swing_lookback + 2) : -2]
        prior_lows = low_prices[-(self.swing_lookback + 2) : -2]
        prior_swing_high = max(prior_highs)
        prior_swing_low = min(prior_lows)

        # Optional Mid-BB for TP2 reference
        bb_result = calculate_bollinger_bands(close_prices, period=20)
        current_mid_bb = bb_result.middle[-1]

        # 6. Evaluate Setup Confluence
        signal_type, reason, metrics = self._evaluate_setup(
            sweep_candle=sweep_candle,
            confirmation_candle=latest_candle,
            prior_swing_high=prior_swing_high,
            prior_swing_low=prior_swing_low,
            sweep_rsi=sweep_rsi,
            current_rsi=current_rsi,
            sweep_vol=volumes[-2],
            avg_vol=avg_vol,
            current_atr=current_atr,
            mid_bb=current_mid_bb,
        )

        if signal_type is SignalType.HOLD:
            return self._hold_signal(candle=latest_candle, reason=reason)

        # 7. Multi-Factor Confidence Scoring
        confidence = self._compute_confidence(
            signal_type=signal_type,
            wick_ratio=metrics[0],
            vol_ratio=metrics[1],
            sweep_rsi=sweep_rsi,
            confirmation_ratio=metrics[2],
        )

        if confidence < self.min_confidence:
            return self._hold_signal(
                candle=latest_candle,
                reason=(
                    f"Confidence {confidence:.2f} below threshold "
                    f"{self.min_confidence:.2f}"
                ),
                confidence=confidence,
            )

        return Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=latest_candle.close_price,
            confidence=confidence,
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            reason=reason,
        )

    def _evaluate_setup(
        self,
        *,
        sweep_candle: Candle,
        confirmation_candle: Candle,
        prior_swing_high: Decimal,
        prior_swing_low: Decimal,
        sweep_rsi: Decimal,
        current_rsi: Decimal,
        sweep_vol: Decimal,
        avg_vol: Decimal,
        current_atr: Decimal,
        mid_bb: Decimal,
    ) -> tuple[SignalType, str, tuple[Decimal, Decimal, Decimal]]:
        """Evaluate Bullish and Bearish Liquidity Sweep Exhaustion rules."""
        sweep_high = sweep_candle.high_price
        sweep_low = sweep_candle.low_price
        sweep_open = sweep_candle.open_price
        sweep_close = sweep_candle.close_price
        sweep_range = sweep_high - sweep_low

        if sweep_range <= _DECIMAL_ZERO:
            return (
                SignalType.HOLD,
                "Zero candle range on sweep candidate",
                (_DECIMAL_ZERO, _DECIMAL_ZERO, _DECIMAL_ZERO),
            )

        sweep_midpoint = (sweep_high + sweep_low) / _DECIMAL_TWO
        conf_close = confirmation_candle.close_price
        conf_ratio = (
            (conf_close - sweep_low) / sweep_range
            if sweep_range > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )

        # --- BULLISH LIQUIDITY SWEEP (BUY) ---
        # 1. Lower Low Sweep: Low dipped below prior swing low
        is_bullish_sweep = sweep_low < prior_swing_low
        # 2. Long Lower Wick: Wick >= 50% of candle range
        lower_body_edge = min(sweep_open, sweep_close)
        lower_wick = lower_body_edge - sweep_low
        lower_wick_ratio = lower_wick / sweep_range
        # 3. Volume Climax: Volume >= 1.3x average
        vol_ratio = sweep_vol / avg_vol
        is_bullish_vol = vol_ratio >= self.volume_multiplier
        # 4. RSI Extremity: RSI <= 38.0
        is_bullish_rsi = (
            sweep_rsi <= self.rsi_oversold or current_rsi <= self.rsi_oversold
        )
        # 5. Confirmation: Close above sweep midpoint
        is_bullish_confirmation = conf_close > sweep_midpoint

        if (
            is_bullish_sweep
            and lower_wick_ratio >= self.min_wick_ratio
            and is_bullish_vol
            and is_bullish_rsi
            and is_bullish_confirmation
        ):
            # Dynamic Risk & Exits
            raw_risk = conf_close - sweep_low + (current_atr * Decimal("0.10"))
            min_risk = current_atr * self.atr_multiplier_sl
            risk_dist = (
                max(raw_risk, min_risk)
                if current_atr > _DECIMAL_ZERO
                else conf_close * Decimal("0.007")
            )
            tp1_dist = risk_dist * self.atr_multiplier_tp1
            tp2_dist = risk_dist * self.atr_multiplier_tp2

            reason = (
                f"Bullish Liquidity Sweep: Low sweep ({sweep_low:.2f} < "
                f"{prior_swing_low:.2f}), Wick {lower_wick_ratio:.1%}, "
                f"Vol {vol_ratio:.1f}x, Mid-conf {conf_close:.2f} > "
                f"{sweep_midpoint:.2f} (SL: -{risk_dist:.2f}, "
                f"TP1: +{tp1_dist:.2f}, TP2: +{tp2_dist:.2f}, Mid-BB: {mid_bb:.2f})"
            )
            return (
                SignalType.BUY,
                reason,
                (lower_wick_ratio, vol_ratio, conf_ratio),
            )

        # --- BEARISH LIQUIDITY SWEEP (SELL - Asymmetric) ---
        # 1. Higher High Sweep: High pierced above prior swing high
        is_bearish_sweep = sweep_high > prior_swing_high
        # 2. Long Upper Wick: Wick >= 50% of candle range
        upper_body_edge = max(sweep_open, sweep_close)
        upper_wick = sweep_high - upper_body_edge
        upper_wick_ratio = upper_wick / sweep_range
        # 3. Volume Climax: Asymmetric threshold (1.25x vs 1.30x)
        effective_vol_mult = self.volume_multiplier - _SHORT_VOLUME_TOLERANCE
        is_bearish_vol = vol_ratio >= effective_vol_mult
        # 4. RSI Extremity: Asymmetric threshold (60 vs 62)
        effective_rsi_overbought = self.rsi_overbought - _SHORT_RSI_TOLERANCE
        is_bearish_rsi = (
            sweep_rsi >= effective_rsi_overbought
            or current_rsi >= effective_rsi_overbought
        )
        # 5. Confirmation: Close below sweep midpoint
        is_bearish_confirmation = conf_close < sweep_midpoint

        if (
            is_bearish_sweep
            and upper_wick_ratio >= self.min_wick_ratio
            and is_bearish_vol
            and is_bearish_rsi
            and is_bearish_confirmation
        ):
            raw_risk = sweep_high - conf_close + (current_atr * Decimal("0.10"))
            min_risk = current_atr * self.atr_multiplier_sl
            risk_dist = (
                max(raw_risk, min_risk)
                if current_atr > _DECIMAL_ZERO
                else conf_close * Decimal("0.007")
            )
            tp1_dist = risk_dist * self.atr_multiplier_tp1
            tp2_dist = risk_dist * self.atr_multiplier_tp2

            reason = (
                f"Bearish Liquidity Sweep: High sweep ({sweep_high:.2f} > "
                f"{prior_swing_high:.2f}), Wick {upper_wick_ratio:.1%}, "
                f"Vol {vol_ratio:.1f}x, Mid-conf {conf_close:.2f} < "
                f"{sweep_midpoint:.2f} (SL: -{risk_dist:.2f}, "
                f"TP1: +{tp1_dist:.2f}, TP2: +{tp2_dist:.2f}, Mid-BB: {mid_bb:.2f})"
            )
            return (
                SignalType.SELL,
                reason,
                (upper_wick_ratio, vol_ratio, _DECIMAL_ONE - conf_ratio),
            )

        return (
            SignalType.HOLD,
            "No liquidity sweep exhaustion pattern confirmed",
            (_DECIMAL_ZERO, _DECIMAL_ZERO, _DECIMAL_ZERO),
        )

    def _compute_confidence(
        self,
        *,
        signal_type: SignalType,
        wick_ratio: Decimal,
        vol_ratio: Decimal,
        sweep_rsi: Decimal,
        confirmation_ratio: Decimal,
    ) -> Decimal:
        """Calculate multi-factor confidence score for verified sweep setups."""
        if signal_type is SignalType.HOLD:
            return _DECIMAL_ZERO

        confidence = _BASE_CONFIDENCE

        # 1. Wick Exhaustion Strength
        if wick_ratio >= _STRONG_WICK_THRESHOLD:
            confidence += _STRONG_WICK_BONUS

        # 2. Volume Climax Surge
        if vol_ratio >= _VOLUME_SURGE_THRESHOLD:
            confidence += _VOLUME_SURGE_BONUS

        # 3. Deep RSI Exhaustion
        if signal_type is SignalType.BUY and sweep_rsi <= _DEEP_RSI_OVERSOLD:
            confidence += _DEEP_RSI_BONUS
        elif signal_type is SignalType.SELL and sweep_rsi >= _DEEP_RSI_OVERBOUGHT:
            confidence += _DEEP_RSI_BONUS

        # 4. Decisive Confirmation Penetration
        if confirmation_ratio >= Decimal("0.75"):
            confidence += _STRONG_CONFIRMATION_BONUS

        # 5. Asymmetric Short Preference
        if signal_type is SignalType.SELL:
            confidence += _SHORT_ASYMMETRY_BONUS
            confidence *= self.short_bias_multiplier

        return min(_MAX_CONFIDENCE, confidence)

    def _is_in_funding_settlement_window(self, candle: Candle) -> bool:
        """Check if candle timestamp falls within 15 mins after funding settlement."""
        utc_dt = (
            candle.close_time.astimezone(timezone.utc)
            if candle.close_time.tzinfo
            else candle.close_time
        )
        return (
            utc_dt.hour in _FUNDING_HOURS
            and utc_dt.minute < self.funding_buffer_minutes
        )

    def _is_under_cooldown(
        self,
        *,
        candles: Sequence[Candle],
        high_prices: Sequence[Decimal],
        low_prices: Sequence[Decimal],
        volumes: Sequence[Decimal],
    ) -> bool:
        """Inspect recent bars to prevent duplicate execution on same sweep."""
        if self.cooldown_bars <= 0:
            return False

        available_bars = min(self.cooldown_bars, len(candles) - 3)
        for offset in range(1, available_bars + 1):
            idx = -2 - offset
            c_high = high_prices[idx]
            c_low = low_prices[idx]
            c_range = c_high - c_low
            if c_range <= _DECIMAL_ZERO:
                continue
            # Check if an earlier bar was also a high-volume rejection candle
            c_open = candles[idx].open_price
            c_close = candles[idx].close_price
            l_wick = min(c_open, c_close) - c_low
            u_wick = c_high - max(c_open, c_close)
            if (
                l_wick / c_range >= self.min_wick_ratio
                or u_wick / c_range >= self.min_wick_ratio
            ):
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
