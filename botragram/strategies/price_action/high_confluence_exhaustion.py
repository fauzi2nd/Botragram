"""
Botragram

Description:
    High Confluence Exhaustion strategy combining Bollinger Bands, RSI,
    ADX regime filter, Volume displacement, HTF EMA trend, and Liquidity
    Sweep / Rejection wicks for ultra high win-rate mean reversion.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import SignalType, StrategyType
from botragram.indicators.momentum.rsi import calculate_rsi
from botragram.indicators.trend.adx import calculate_adx
from botragram.indicators.trend.ema import calculate_ema
from botragram.indicators.trend.sma import calculate_sma
from botragram.indicators.volatility.bollinger_bands import (
    calculate_bollinger_bands,
)
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "HighConfluenceExhaustionStrategy",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Decimal = Decimal("0")
_DECIMAL_ONE: Decimal = Decimal("1")
_DECIMAL_BASE_CONFIDENCE: Decimal = Decimal("0.65")
_DECIMAL_MIN_CONFIDENCE: Decimal = Decimal("0.60")
_DECIMAL_MAX_CONFIDENCE: Decimal = Decimal("0.95")
_DECIMAL_PROXIMITY_THRESHOLD: Decimal = Decimal("0.01")
_DECIMAL_NEUTRAL_ADX_CAP: Decimal = Decimal("25.0")
_DECIMAL_MIN_WICK_RATIO: Decimal = Decimal("0.30")
_DECIMAL_STRONG_WICK_RATIO: Decimal = Decimal("0.40")
_DECIMAL_DEEP_WICK_RATIO: Decimal = Decimal("0.50")
_DECIMAL_RSI_DEEP_LONG: Decimal = Decimal("20.0")
_DECIMAL_RSI_EXTREME_LONG: Decimal = Decimal("15.0")
_DECIMAL_RSI_DEEP_SHORT: Decimal = Decimal("80.0")
_DECIMAL_RSI_EXTREME_SHORT: Decimal = Decimal("85.0")
_DECIMAL_VOLUME_HIGH_MULT: Decimal = Decimal("1.50")
_DECIMAL_VOLUME_CLIMAX_MULT: Decimal = Decimal("2.00")
_DECIMAL_STEP_BONUS: Decimal = Decimal("0.05")
_DECIMAL_LARGE_BONUS: Decimal = Decimal("0.10")


# =============================================================================
# Strategy Class
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class HighConfluenceExhaustionStrategy(BaseStrategy):
    """High win-rate mean-reversion strategy seeking extreme exhaustion confluence."""

    bb_period: int = 20
    bb_std_dev: Decimal = Decimal("2.0")
    rsi_period: int = 14
    rsi_oversold: Decimal = Decimal("28.0")
    rsi_overbought: Decimal = Decimal("72.0")
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.3")
    adx_period: int = 14
    adx_max_threshold: Decimal = Decimal("42.0")
    trend_period: int = 50
    swing_lookback: int = 10

    def __post_init__(self) -> None:
        """Validate bounded strategy settings."""
        if self.bb_period <= 0:
            raise ValueError("Bollinger Bands period must be positive")
        if self.bb_std_dev <= _DECIMAL_ZERO:
            raise ValueError("Bollinger Bands standard deviation must be positive")
        if self.rsi_period <= 0:
            raise ValueError("RSI period must be positive")
        if not (
            _DECIMAL_ZERO <= self.rsi_oversold < self.rsi_overbought <= Decimal("100")
        ):
            raise ValueError("RSI thresholds must be bounded within [0, 100]")
        if self.volume_period <= 0 or self.volume_multiplier <= _DECIMAL_ZERO:
            raise ValueError("Volume parameters must be positive")
        if self.adx_period <= 0 or self.adx_max_threshold <= _DECIMAL_ZERO:
            raise ValueError("ADX parameters must be positive")
        if self.trend_period <= 0 or self.swing_lookback <= 0:
            raise ValueError("Lookback periods must be positive")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.HIGH_CONFLUENCE_EXHAUSTION

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required for evaluation."""
        return max(
            self.trend_period + 1,
            self.bb_period + 1,
            self.rsi_period + 2,
            self.adx_period * 2 + 1,
            self.volume_period + self.swing_lookback + 1,
        )

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a trading signal from extreme exhaustion confluence."""
        self.validate_candles(candles=candles)

        high_prices = tuple(candle.high_price for candle in candles)
        low_prices = tuple(candle.low_price for candle in candles)
        close_prices = tuple(candle.close_price for candle in candles)
        volumes = tuple(candle.volume for candle in candles)

        latest_candle = candles[-1]
        symbol = latest_candle.symbol
        as_of = latest_candle.close_time
        close_price = latest_candle.close_price

        # 1. ADX Runaway Trend Filter
        adx_result = calculate_adx(
            high_prices,
            low_prices,
            close_prices,
            period=self.adx_period,
        )
        latest_adx = adx_result.adx[-1] if adx_result.adx else _DECIMAL_ZERO
        if latest_adx > self.adx_max_threshold:
            return Signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                price=close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=as_of,
                reason=(
                    f"ADX {latest_adx:.1f} exceeds runaway threshold "
                    f"{self.adx_max_threshold:.1f}"
                ),
            )

        # 2. HTF Trend Baseline (EMA 200)
        ema_values = calculate_ema(close_prices, period=self.trend_period)
        latest_ema = ema_values[-1]

        # 3. Bollinger Bands (20, 2.5)
        bb_result = calculate_bollinger_bands(
            close_prices,
            period=self.bb_period,
            standard_deviation=self.bb_std_dev,
        )
        latest_upper_bb = bb_result.upper[-1]
        latest_lower_bb = bb_result.lower[-1]

        # 4. RSI (14)
        rsi_values = calculate_rsi(close_prices, period=self.rsi_period)
        latest_rsi = rsi_values[-1]

        # 5. Volume Displacement (SMA 20)
        volume_sma_values = calculate_sma(volumes, period=self.volume_period)
        latest_volume_sma = volume_sma_values[-1]
        has_volume_displacement = latest_candle.volume >= (
            latest_volume_sma * self.volume_multiplier
        )

        if not has_volume_displacement:
            return Signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                price=close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=as_of,
                reason="Insufficient volume displacement for reversal confirmation",
            )

        # 6. Candle Range and Wicks
        total_range = latest_candle.high_price - latest_candle.low_price
        if total_range <= _DECIMAL_ZERO:
            return Signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                price=close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=as_of,
                reason="Zero-range candle cannot confirm rejection",
            )

        lower_wick = (
            min(latest_candle.open_price, latest_candle.close_price)
            - latest_candle.low_price
        )
        upper_wick = latest_candle.high_price - max(
            latest_candle.open_price, latest_candle.close_price
        )
        lower_wick_ratio = lower_wick / total_range
        upper_wick_ratio = upper_wick / total_range

        # 7. Previous Swing Low/High Lookback
        lookback_slice = candles[-1 - self.swing_lookback : -1]
        prior_swing_low = min(c.low_price for c in lookback_slice)
        prior_swing_high = max(c.high_price for c in lookback_slice)

        # LONG Confluence Check
        is_long_neutral_or_bullish = (
            close_price >= latest_ema
            or latest_adx < _DECIMAL_NEUTRAL_ADX_CAP
            or ((latest_ema - close_price) / close_price)
            <= _DECIMAL_PROXIMITY_THRESHOLD
            or lower_wick_ratio >= _DECIMAL_STRONG_WICK_RATIO
        )
        touches_lower_bb = latest_candle.low_price <= latest_lower_bb
        is_rsi_oversold = latest_rsi <= self.rsi_oversold

        has_long_sweep = (
            latest_candle.low_price < prior_swing_low and close_price > prior_swing_low
        )
        has_long_rejection = (
            lower_wick_ratio >= _DECIMAL_MIN_WICK_RATIO
            and close_price > (latest_candle.low_price + total_range * Decimal("0.35"))
        )
        long_rejection_confirmed = has_long_sweep or has_long_rejection

        if (
            is_long_neutral_or_bullish
            and touches_lower_bb
            and is_rsi_oversold
            and long_rejection_confirmed
        ):
            confidence = self._calculate_confidence(
                is_long=True,
                rsi=latest_rsi,
                volume=latest_candle.volume,
                volume_sma=latest_volume_sma,
                has_sweep=has_long_sweep,
                wick_ratio=lower_wick_ratio,
            )
            return Signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                price=close_price,
                confidence=confidence,
                strategy_name=self.strategy_type.value,
                generated_at=as_of,
                reason=(
                    f"Long exhaustion confluence (RSI {latest_rsi:.1f} <= "
                    f"{self.rsi_oversold:.1f}, Low <= Lower BB, "
                    f"Vol {latest_candle.volume:.1f} >= {self.volume_multiplier}x SMA)"
                ),
            )

        # SHORT Confluence Check
        is_short_neutral_or_bearish = (
            close_price <= latest_ema
            or latest_adx < _DECIMAL_NEUTRAL_ADX_CAP
            or ((close_price - latest_ema) / latest_ema) <= _DECIMAL_PROXIMITY_THRESHOLD
            or upper_wick_ratio >= _DECIMAL_STRONG_WICK_RATIO
        )
        touches_upper_bb = latest_candle.high_price >= latest_upper_bb
        is_rsi_overbought = latest_rsi >= self.rsi_overbought

        has_short_sweep = (
            latest_candle.high_price > prior_swing_high
            and close_price < prior_swing_high
        )
        has_short_rejection = (
            upper_wick_ratio >= _DECIMAL_MIN_WICK_RATIO
            and close_price < (latest_candle.high_price - total_range * Decimal("0.35"))
        )
        short_rejection_confirmed = has_short_sweep or has_short_rejection

        if (
            is_short_neutral_or_bearish
            and touches_upper_bb
            and is_rsi_overbought
            and short_rejection_confirmed
        ):
            confidence = self._calculate_confidence(
                is_long=False,
                rsi=latest_rsi,
                volume=latest_candle.volume,
                volume_sma=latest_volume_sma,
                has_sweep=has_short_sweep,
                wick_ratio=upper_wick_ratio,
            )
            return Signal(
                symbol=symbol,
                signal_type=SignalType.SELL,
                price=close_price,
                confidence=confidence,
                strategy_name=self.strategy_type.value,
                generated_at=as_of,
                reason=(
                    f"Short exhaustion confluence (RSI {latest_rsi:.1f} >= "
                    f"{self.rsi_overbought:.1f}, High >= Upper BB, "
                    f"Vol {latest_candle.volume:.1f} >= {self.volume_multiplier}x SMA)"
                ),
            )

        return Signal(
            symbol=symbol,
            signal_type=SignalType.HOLD,
            price=close_price,
            confidence=_DECIMAL_ZERO,
            strategy_name=self.strategy_type.value,
            generated_at=as_of,
            reason="Exhaustion confluence conditions not met",
        )

    def _calculate_confidence(
        self,
        *,
        is_long: bool,
        rsi: Decimal,
        volume: Decimal,
        volume_sma: Decimal,
        has_sweep: bool,
        wick_ratio: Decimal,
    ) -> Decimal:
        """Calculate dynamic confluence confidence score (0.60 - 0.95)."""
        score = _DECIMAL_BASE_CONFIDENCE

        # 1. Wick Depth Bonus (+0.05 or +0.10)
        if wick_ratio >= _DECIMAL_DEEP_WICK_RATIO:
            score += _DECIMAL_LARGE_BONUS
        elif wick_ratio >= _DECIMAL_STRONG_WICK_RATIO:
            score += _DECIMAL_STEP_BONUS

        # 2. Volume Confirmation Bonus (+0.05 or +0.10)
        if volume >= (volume_sma * _DECIMAL_VOLUME_CLIMAX_MULT):
            score += _DECIMAL_LARGE_BONUS
        elif volume >= (volume_sma * _DECIMAL_VOLUME_HIGH_MULT):
            score += _DECIMAL_STEP_BONUS

        # 3. RSI Exhaustion Depth Bonus (+0.05 or +0.10)
        if is_long:
            if rsi <= _DECIMAL_RSI_EXTREME_LONG:
                score += _DECIMAL_LARGE_BONUS
            elif rsi <= _DECIMAL_RSI_DEEP_LONG:
                score += _DECIMAL_STEP_BONUS
        else:
            if rsi >= _DECIMAL_RSI_EXTREME_SHORT:
                score += _DECIMAL_LARGE_BONUS
            elif rsi >= _DECIMAL_RSI_DEEP_SHORT:
                score += _DECIMAL_STEP_BONUS

        # 4. Liquidity Sweep Bonus (+0.05)
        if has_sweep:
            score += _DECIMAL_STEP_BONUS

        return min(_DECIMAL_MAX_CONFIDENCE, max(_DECIMAL_MIN_CONFIDENCE, score))
