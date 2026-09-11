"""
Botragram

Description:
    Market Orderflow Regime & Price-Hunt (MORPH) strategy.
    Combines Market Structure (Swing / CHoCH), Price-Hunt (Liquidity Sweep
    and FVG Tap), Candlestick Rejection Trigger, Volume, and Open Interest
    Flow into a unified quantitative trading pipeline.

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
from botragram.enums import PositionSide, SignalType, StrategyType
from botragram.indicators import (
    calculate_atr,
    detect_engulfing,
    detect_pinbar,
)
from botragram.indicators.price_action import (
    detect_fvg_zones,
    find_swing_levels,
)
from botragram.indicators.trend.ema import calculate_ema
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "MorphStrategy",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_ONE: Final[Decimal] = Decimal("1")
_DECIMAL_TWO: Final[Decimal] = Decimal("2")
_MAX_CONFIDENCE: Final[Decimal] = Decimal("0.95")
_STRONG_WICK_BONUS_RATIO: Final[Decimal] = Decimal("0.60")
_SURGE_VOLUME_FACTOR: Final[Decimal] = Decimal("1.40")


# =============================================================================
# Strategy Class
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class MorphStrategy(BaseStrategy):
    """Market Orderflow Regime & Price-Hunt (MORPH) quantitative strategy.

    Orchestrates a 5-layer execution funnel:
    1. Market Regime & Structure: Swing High / Swing Low identification.
    2. Price-Hunt: Liquidity Sweep of swing boundaries or FVG mitigation tap.
    3. Candlestick Trigger: Bullish/Bearish Pinbar rejection or Engulfing bar.
    4. Orderflow & Volume: Volume surge verification and Open Interest regime.
    5. Structural Risk Filter: ATR-anchored structural invalidation level.
    """

    # Structure & Hunt Parameters
    swing_lookback: int = 15
    fvg_lookback: int = 20
    use_fvg: bool = True

    # Candlestick Trigger Parameters
    min_wick_ratio: Decimal = Decimal("0.50")
    max_opposite_wick_ratio: Decimal = Decimal("0.25")
    min_engulfing_body_ratio: Decimal = Decimal("1.05")

    # Volume & Orderflow Parameters
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.15")

    # Risk & Structural Sizing
    atr_period: int = 14
    atr_multiplier_sl: Decimal = Decimal("0.8")
    risk_reward_ratio: Decimal = Decimal("2.0")
    min_confidence: Decimal = Decimal("0.65")

    # Macro Trend & Volatility Filter
    trend_period: int = 200
    intermediate_trend_period: int = 50
    require_trend_filter: bool = True
    min_natr_threshold: Decimal = Decimal("0.0020")

    # Open Interest Integration
    use_open_interest: bool = True
    min_oi_change_pct: Decimal = Decimal("0.0")
    oi_confidence_bonus: Decimal = Decimal("0.05")
    require_oi_confluence: bool = False

    # Funding Sentiment Integration
    filter_funding_sentiment: bool = True
    max_long_funding_rate: Decimal = Decimal("0.0005")
    min_short_funding_rate: Decimal = Decimal("-0.0005")
    require_funding_sentiment: bool = True

    def __post_init__(self) -> None:
        """Validate bounded MORPH strategy parameters."""
        if self.swing_lookback <= 2:
            raise ValueError("swing_lookback must be greater than 2")
        if self.fvg_lookback <= 2:
            raise ValueError("fvg_lookback must be greater than 2")
        if self.volume_period <= 2:
            raise ValueError("volume_period must be greater than 2")
        if self.volume_multiplier <= _DECIMAL_ZERO:
            raise ValueError("volume_multiplier must be greater than zero")
        if self.atr_period <= 2:
            raise ValueError("atr_period must be greater than 2")
        if self.atr_multiplier_sl <= _DECIMAL_ZERO:
            raise ValueError("atr_multiplier_sl must be greater than zero")
        if self.risk_reward_ratio <= _DECIMAL_ZERO:
            raise ValueError("risk_reward_ratio must be greater than zero")
        if not (_DECIMAL_ZERO <= self.min_confidence <= _DECIMAL_ONE):
            raise ValueError("min_confidence must be between 0.0 and 1.0")
        if self.trend_period <= 0:
            raise ValueError("trend_period must be greater than zero")
        if self.intermediate_trend_period <= 0:
            raise ValueError("intermediate_trend_period must be greater than zero")
        if self.intermediate_trend_period >= self.trend_period:
            raise ValueError("intermediate_trend_period must be less than trend_period")
        if self.min_natr_threshold < _DECIMAL_ZERO:
            raise ValueError("min_natr_threshold must not be negative")
        if self.min_short_funding_rate > self.max_long_funding_rate:
            raise ValueError(
                "min_short_funding_rate cannot exceed max_long_funding_rate"
            )

    @property
    def strategy_type(self) -> StrategyType:
        """Return the unique StrategyType identifier."""
        return StrategyType.MORPH

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candles required to calculate all layers."""
        base_min = (
            max(
                self.swing_lookback * 2 + 1,
                self.volume_period + 1,
                self.fvg_lookback + 1,
                self.atr_period + 1,
            )
            + 2
        )
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
        """Generate a trading signal through the 5-layer MORPH pipeline."""
        self.validate_candles(candles=candles)

        high_prices = tuple(c.high_price for c in candles)
        low_prices = tuple(c.low_price for c in candles)
        close_prices = tuple(c.close_price for c in candles)
        volumes = tuple(c.volume for c in candles)

        curr_candle = candles[-1]
        prev_candle = candles[-2]

        # ---------------------------------------------------------------------
        # Layer 1: Market Structure (Swing Levels)
        # ---------------------------------------------------------------------
        # Evaluate swings excluding the current incomplete / forming candle bar
        last_swing_high, last_swing_low = find_swing_levels(
            high_prices=high_prices[:-1],
            low_prices=low_prices[:-1],
            swing_window=self.swing_lookback,
        )

        # ---------------------------------------------------------------------
        # Layer 2: Price-Hunt (Liquidity Sweep & FVG Tap)
        # ---------------------------------------------------------------------
        bullish_sweep = False
        bearish_sweep = False

        if last_swing_low is not None:
            # Bullish Sweep: Price dipped below swing low and closed back above
            if curr_candle.low_price < last_swing_low <= curr_candle.close_price:
                bullish_sweep = True

        if last_swing_high is not None:
            # Bearish Sweep: Price pierced above swing high and closed back below
            if curr_candle.high_price > last_swing_high >= curr_candle.close_price:
                bearish_sweep = True

        bullish_fvg_tap = False
        bearish_fvg_tap = False
        if self.use_fvg:
            fvg_zones = detect_fvg_zones(
                high_prices=high_prices[:-1],
                low_prices=low_prices[:-1],
                close_prices=close_prices[:-1],
                lookback=self.fvg_lookback,
            )
            for fvg in fvg_zones:
                if fvg.mitigated:
                    continue
                if (
                    fvg.is_bullish
                    and curr_candle.low_price <= fvg.top
                    and curr_candle.close_price >= fvg.bottom
                ):
                    bullish_fvg_tap = True
                elif (
                    not fvg.is_bullish
                    and curr_candle.high_price >= fvg.bottom
                    and curr_candle.close_price <= fvg.top
                ):
                    bearish_fvg_tap = True

        has_bullish_hunt = bullish_sweep or bullish_fvg_tap
        has_bearish_hunt = bearish_sweep or bearish_fvg_tap

        if not has_bullish_hunt and not has_bearish_hunt:
            return Signal(
                symbol=curr_candle.symbol,
                signal_type=SignalType.HOLD,
                price=curr_candle.close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=curr_candle.close_time,
                reason="No liquidity sweep or FVG price-hunt detected",
            )

        # ---------------------------------------------------------------------
        # Layer 3: Candlestick Rejection Trigger
        # ---------------------------------------------------------------------
        pinbar_match = detect_pinbar(
            candle=curr_candle,
            min_wick_ratio=self.min_wick_ratio,
            max_opposite_wick_ratio=self.max_opposite_wick_ratio,
        )
        engulfing_match = detect_engulfing(
            prev_candle=prev_candle,
            curr_candle=curr_candle,
            min_body_ratio=self.min_engulfing_body_ratio,
        )

        is_bullish_trigger = (
            pinbar_match.matched and pinbar_match.side is PositionSide.LONG
        ) or (engulfing_match.matched and engulfing_match.side is PositionSide.LONG)

        is_bearish_trigger = (
            pinbar_match.matched and pinbar_match.side is PositionSide.SHORT
        ) or (engulfing_match.matched and engulfing_match.side is PositionSide.SHORT)

        signal_type = SignalType.HOLD
        hunt_reason = ""

        if has_bullish_hunt and is_bullish_trigger:
            signal_type = SignalType.BUY
            hunt_type = "Sweep" if bullish_sweep else "FVG Tap"
            trigger_type = (
                "Pinbar"
                if pinbar_match.matched and pinbar_match.side is PositionSide.LONG
                else "Engulfing"
            )
            hunt_reason = f"Bullish {hunt_type} + {trigger_type} Rejection"
        elif has_bearish_hunt and is_bearish_trigger:
            signal_type = SignalType.SELL
            hunt_type = "Sweep" if bearish_sweep else "FVG Tap"
            trigger_type = (
                "Pinbar"
                if pinbar_match.matched and pinbar_match.side is PositionSide.SHORT
                else "Engulfing"
            )
            hunt_reason = f"Bearish {hunt_type} + {trigger_type} Rejection"
        else:
            return Signal(
                symbol=curr_candle.symbol,
                signal_type=SignalType.HOLD,
                price=curr_candle.close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=curr_candle.close_time,
                reason=(
                    "Price-hunt detected without matching candlestick rejection trigger"
                ),
            )

        # ---------------------------------------------------------------------
        # Macro Trend Alignment Filter
        # ---------------------------------------------------------------------
        if self.require_trend_filter and len(close_prices) >= self.trend_period:
            ema_macro = calculate_ema(close_prices, period=self.trend_period)[-1]
            ema_inter = calculate_ema(
                close_prices, period=self.intermediate_trend_period
            )[-1]
            latest_close = curr_candle.close_price

            is_macro_bearish = ema_inter < ema_macro
            is_macro_bullish = ema_inter > ema_macro

            trend_ok_for_buy = (latest_close >= ema_macro) and not is_macro_bearish
            trend_ok_for_sell = (latest_close <= ema_macro) and not is_macro_bullish

            if signal_type is SignalType.BUY and not trend_ok_for_buy:
                return Signal(
                    symbol=curr_candle.symbol,
                    signal_type=SignalType.HOLD,
                    price=curr_candle.close_price,
                    confidence=_DECIMAL_ZERO,
                    strategy_name=self.strategy_type.value,
                    generated_at=curr_candle.close_time,
                    reason="Bullish MORPH rejected: below trend EMA or macro downtrend",
                )
            if signal_type is SignalType.SELL and not trend_ok_for_sell:
                return Signal(
                    symbol=curr_candle.symbol,
                    signal_type=SignalType.HOLD,
                    price=curr_candle.close_price,
                    confidence=_DECIMAL_ZERO,
                    strategy_name=self.strategy_type.value,
                    generated_at=curr_candle.close_time,
                    reason="Bearish MORPH rejected: above trend EMA or macro uptrend",
                )

        # ---------------------------------------------------------------------
        # Layer 4: Volume & Orderflow Participation
        # ---------------------------------------------------------------------
        recent_vols = volumes[-(self.volume_period + 1) : -1]
        avg_vol = (
            sum(recent_vols) / Decimal(str(len(recent_vols)))
            if recent_vols
            else _DECIMAL_ZERO
        )

        volume_confirmed = curr_candle.volume >= (avg_vol * self.volume_multiplier)
        if not volume_confirmed:
            return Signal(
                symbol=curr_candle.symbol,
                signal_type=SignalType.HOLD,
                price=curr_candle.close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=curr_candle.close_time,
                reason="Volume below participation threshold for MORPH setup",
            )

        # ---------------------------------------------------------------------
        # Layer 5: ATR & Structural Invalidation Targets
        # ---------------------------------------------------------------------
        atr_series = calculate_atr(
            high_prices,
            low_prices,
            close_prices,
            period=self.atr_period,
        )
        current_atr = atr_series[-1] if atr_series else _DECIMAL_ZERO

        # Dead Market Volatility Gate (NATR)
        if (
            self.min_natr_threshold > _DECIMAL_ZERO
            and curr_candle.close_price > _DECIMAL_ZERO
        ):
            natr = current_atr / curr_candle.close_price
            if natr < self.min_natr_threshold:
                return Signal(
                    symbol=curr_candle.symbol,
                    signal_type=SignalType.HOLD,
                    price=curr_candle.close_price,
                    confidence=_DECIMAL_ZERO,
                    strategy_name=self.strategy_type.value,
                    generated_at=curr_candle.close_time,
                    reason=(
                        f"Dead market volatility rejected "
                        f"(NATR {natr:.4f} < {self.min_natr_threshold})"
                    ),
                )

        if signal_type is SignalType.BUY:
            ref_low = (
                min(curr_candle.low_price, last_swing_low)
                if last_swing_low is not None
                else curr_candle.low_price
            )
            stop_loss = ref_low - (current_atr * self.atr_multiplier_sl)
            risk_dist = curr_candle.close_price - stop_loss
            take_profit = curr_candle.close_price + (risk_dist * self.risk_reward_ratio)
        else:
            ref_high = (
                max(curr_candle.high_price, last_swing_high)
                if last_swing_high is not None
                else curr_candle.high_price
            )
            stop_loss = ref_high + (current_atr * self.atr_multiplier_sl)
            risk_dist = stop_loss - curr_candle.close_price
            take_profit = curr_candle.close_price - (risk_dist * self.risk_reward_ratio)

        # ---------------------------------------------------------------------
        # Composite Confidence Score
        # ---------------------------------------------------------------------
        confidence = self._compute_confidence(
            is_sweep=bullish_sweep or bearish_sweep,
            is_fvg=bullish_fvg_tap or bearish_fvg_tap,
            pinbar_match=pinbar_match,
            curr_volume=curr_candle.volume,
            avg_volume=avg_vol,
        )

        full_reason = (
            f"{hunt_reason} | Invalidation: {stop_loss:.5f} | Target: {take_profit:.5f}"
        )

        candidate_signal = Signal(
            symbol=curr_candle.symbol,
            signal_type=signal_type,
            price=curr_candle.close_price,
            confidence=confidence,
            strategy_name=self.strategy_type.value,
            generated_at=curr_candle.close_time,
            reason=full_reason,
        )

        # ---------------------------------------------------------------------
        # Open Interest Confluence Filter
        # ---------------------------------------------------------------------
        if self.use_open_interest:
            candidate_signal = self.apply_open_interest_confluence(
                signal=candidate_signal,
                candles=candles,
                min_change_pct=self.min_oi_change_pct,
                confidence_bonus=self.oi_confidence_bonus,
                strict=self.require_oi_confluence,
            )

        # ---------------------------------------------------------------------
        # Funding Rate Crowding Sentiment Filter
        # ---------------------------------------------------------------------
        if self.filter_funding_sentiment:
            candidate_signal = self.apply_funding_sentiment_filter(
                signal=candidate_signal,
                candles=candles,
                max_long_funding=self.max_long_funding_rate,
                min_short_funding=self.min_short_funding_rate,
                strict=self.require_funding_sentiment,
            )

        return candidate_signal

    def _compute_confidence(
        self,
        *,
        is_sweep: bool,
        is_fvg: bool,
        pinbar_match: object,
        curr_volume: Decimal,
        avg_volume: Decimal,
    ) -> Decimal:
        """Compute composite confidence score from multi-layer alignment."""
        score = self.min_confidence

        if is_sweep:
            score += Decimal("0.08")
        if is_fvg:
            score += Decimal("0.05")

        from botragram.indicators.price_action.candlesticks import CandlestickMatch

        if isinstance(pinbar_match, CandlestickMatch):
            if (
                pinbar_match.matched
                and pinbar_match.wick_ratio >= _STRONG_WICK_BONUS_RATIO
            ):
                score += Decimal("0.06")

        if avg_volume > _DECIMAL_ZERO and curr_volume >= (
            avg_volume * _SURGE_VOLUME_FACTOR
        ):
            score += Decimal("0.05")

        return min(_MAX_CONFIDENCE, score)
