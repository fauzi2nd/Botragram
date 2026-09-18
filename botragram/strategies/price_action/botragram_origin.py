"""
Botragram

Description:
    Botragram Origin strategy driven by a comprehensive Japanese candlestick
    pattern recognition engine (Single, Dual, and Triple candle patterns)
    with extensible hooks for technical analysis.

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
from botragram.enums import PositionSide, SignalType, StrategyType
from botragram.indicators import (
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_psar,
    calculate_rsi,
)
from botragram.indicators.price_action import (
    CandlestickMatch,
    detect_all_candlestick_patterns,
)
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "BotragramOriginStrategy",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_ONE: Final[Decimal] = Decimal("1")
_DECIMAL_MAX_CONFIDENCE: Final[Decimal] = Decimal("0.95")
_MAX_CONFLUENCE_BONUS: Final[Decimal] = Decimal("0.06")
_MAX_TA_BONUS: Final[Decimal] = Decimal("0.05")
_MAX_SAFE_SL_PCT: Final[Decimal] = Decimal("0.50")
_DEFAULT_MINIMUM_CANDLES: Final[int] = 5
_RSI_OVERSOLD_BONUS_THRESHOLD: Final[Decimal] = Decimal("35.0")
_RSI_OVERBOUGHT_BONUS_THRESHOLD: Final[Decimal] = Decimal("65.0")

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_TRIPLE_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "morning_star",
        "evening_star",
        "three_white_soldiers",
        "three_black_crows",
        "three_inside_up",
        "three_inside_down",
    }
)
_DUAL_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "bullish_engulfing",
        "bearish_engulfing",
        "piercing_line",
        "dark_cloud_cover",
        "tweezer_bottom",
        "tweezer_top",
    }
)
_HARAMI_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "bullish_harami",
        "bearish_harami",
    }
)
_SINGLE_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "bullish_pinbar",
        "bearish_pinbar",
        "bullish_marubozu",
        "bearish_marubozu",
        "dragonfly_doji",
        "gravestone_doji",
    }
)


# =============================================================================
# Strategy Class
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class BotragramOriginStrategy(BaseStrategy):
    """Price-action strategy driven by candlestick pattern recognition."""

    # Risk-Reward and Setup Parameters
    risk_reward_ratio: Decimal = Decimal("1.5")
    min_sl_pct: Decimal = Decimal("0.010")
    max_sl_pct: Decimal = Decimal("0.030")
    fallback_sl_pct: Decimal = Decimal("0.015")
    min_confidence: Decimal = Decimal("0.70")

    # Extensible Technical Analysis Hooks (for future TA phases)
    use_trend_filter: bool = False
    trend_ema_period: int = 50
    use_volume_filter: bool = False
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.0")
    use_rsi_filter: bool = False
    rsi_period: int = 14
    rsi_long_max: Decimal = Decimal("70.0")
    rsi_short_min: Decimal = Decimal("30.0")
    require_rsi_direction: bool = False
    use_bb_filter: bool = False
    bb_period: int = 20
    bb_std_dev: Decimal = Decimal("2.0")
    use_macd_filter: bool = False
    macd_fast_period: int = 12
    macd_slow_period: int = 26
    macd_signal_period: int = 9
    use_psar_filter: bool = False
    psar_max_proximity_pct: Decimal = Decimal("0.008")

    def __post_init__(self) -> None:
        """Validate strategy parameter invariants."""
        if self.risk_reward_ratio <= _DECIMAL_ZERO:
            raise ValueError("risk_reward_ratio must be positive")

        if self.min_sl_pct <= _DECIMAL_ZERO:
            raise ValueError("min_sl_pct must be positive")

        if self.max_sl_pct <= _DECIMAL_ZERO:
            raise ValueError("max_sl_pct must be positive")

        if self.max_sl_pct < self.min_sl_pct:
            raise ValueError("min_sl_pct cannot exceed max_sl_pct")

        if self.max_sl_pct >= _MAX_SAFE_SL_PCT:
            raise ValueError(
                f"max_sl_pct ({self.max_sl_pct}) must be less than {_MAX_SAFE_SL_PCT}"
            )

        if not (self.min_sl_pct <= self.fallback_sl_pct <= self.max_sl_pct):
            raise ValueError(
                f"fallback_sl_pct ({self.fallback_sl_pct}) must be between "
                f"min_sl_pct ({self.min_sl_pct}) and max_sl_pct ({self.max_sl_pct})"
            )

        if not (_DECIMAL_ZERO < self.min_confidence <= _DECIMAL_ONE):
            raise ValueError("min_confidence must be between 0.0 (exclusive) and 1.0")

        if self.trend_ema_period <= 0:
            raise ValueError("trend_ema_period must be greater than zero")

        if self.volume_period <= 0:
            raise ValueError("volume_period must be greater than zero")

        if self.volume_multiplier <= _DECIMAL_ZERO:
            raise ValueError("volume_multiplier must be positive")

        if self.rsi_period <= 0:
            raise ValueError("rsi_period must be greater than zero")

        if not (_DECIMAL_ZERO <= self.rsi_long_max <= Decimal("100")):
            raise ValueError("rsi_long_max must be between 0.0 and 100.0")

        if not (_DECIMAL_ZERO <= self.rsi_short_min <= Decimal("100")):
            raise ValueError("rsi_short_min must be between 0.0 and 100.0")

        if self.bb_period <= 0:
            raise ValueError("bb_period must be greater than zero")

        if self.bb_std_dev <= _DECIMAL_ZERO:
            raise ValueError("bb_std_dev must be positive")

        if self.macd_fast_period <= 0:
            raise ValueError("macd_fast_period must be greater than zero")

        if self.macd_slow_period <= 0:
            raise ValueError("macd_slow_period must be greater than zero")

        if self.macd_signal_period <= 0:
            raise ValueError("macd_signal_period must be greater than zero")

        if self.macd_fast_period >= self.macd_slow_period:
            raise ValueError("macd_fast_period must be less than macd_slow_period")

        if self.psar_max_proximity_pct <= _DECIMAL_ZERO:
            raise ValueError("psar_max_proximity_pct must be positive")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type enumeration."""
        return StrategyType.BOTRAGRAM_ORIGIN

    @property
    def minimum_candles(self) -> int:
        """Return minimum candle count required for evaluation."""
        return max(
            _DEFAULT_MINIMUM_CANDLES,
            self.trend_ema_period + 5 if self.use_trend_filter else 0,
            self.volume_period + 5 if self.use_volume_filter else 0,
            self.rsi_period + 5 if self.use_rsi_filter else 0,
            self.bb_period + 5 if self.use_bb_filter else 0,
            (
                self.macd_slow_period + self.macd_signal_period + 5
                if self.use_macd_filter
                else 0
            ),
            10 if self.use_psar_filter else 0,
        )

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate trading signal using candlestick pattern recognition.

        Args:
            candles: Chronological sequence of historical candles.

        Returns:
            Signal instance with BUY, SELL, or HOLD recommendation.
        """
        self.validate_candles(candles=candles)

        latest_candle = candles[-1]
        matches = detect_all_candlestick_patterns(candles=candles)

        # Filter matches that have a directional trading bias
        directional_matches = [m for m in matches if m.side is not None]
        if not directional_matches:
            return Signal(
                symbol=latest_candle.symbol,
                signal_type=SignalType.HOLD,
                price=latest_candle.close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=latest_candle.close_time,
                stop_loss=None,
                take_profit=None,
                reason="No directional candlestick pattern detected",
            )

        long_matches = [m for m in directional_matches if m.side is PositionSide.LONG]
        short_matches = [m for m in directional_matches if m.side is PositionSide.SHORT]

        # Check for conflicting patterns
        if long_matches and short_matches:
            long_names = ", ".join(m.pattern_name for m in long_matches)
            short_names = ", ".join(m.pattern_name for m in short_matches)
            _LOGGER.debug(
                "Conflicting patterns detected for %s: Long=[%s] vs Short=[%s]",
                latest_candle.symbol,
                long_names,
                short_names,
            )
            return Signal(
                symbol=latest_candle.symbol,
                signal_type=SignalType.HOLD,
                price=latest_candle.close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=latest_candle.close_time,
                stop_loss=None,
                take_profit=None,
                reason=(
                    f"Conflicting candlestick patterns detected: "
                    f"Long=[{long_names}] vs Short=[{short_names}]"
                ),
            )

        active_matches = long_matches if long_matches else short_matches
        best_match, raw_confidence = self._score_patterns(active_matches)

        if raw_confidence < self.min_confidence:
            return Signal(
                symbol=latest_candle.symbol,
                signal_type=SignalType.HOLD,
                price=latest_candle.close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=latest_candle.close_time,
                stop_loss=None,
                take_profit=None,
                reason=(
                    f"Pattern {best_match.pattern_name} confidence "
                    f"({raw_confidence:.2f}) below threshold {self.min_confidence}"
                ),
            )

        signal_type = (
            SignalType.BUY if best_match.side is PositionSide.LONG else SignalType.SELL
        )
        pattern_names_str = ", ".join(m.pattern_name for m in active_matches)

        # Calculate Stop Loss and Take Profit
        sl_price, tp_price = self.calculate_exits(
            signal_type=signal_type,
            current_price=latest_candle.close_price,
            rejection_level=best_match.rejection_level,
        )

        signal = Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=latest_candle.close_price,
            confidence=raw_confidence,
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            stop_loss=sl_price,
            take_profit=tp_price,
            reason=f"Botragram Origin: {pattern_names_str}",
        )

        return self._apply_ta_filters(signal=signal, candles=candles)

    @staticmethod
    def _pattern_quality_bonus(match: CandlestickMatch) -> Decimal:
        """Calculate quality bonus based on candlestick geometric ratios.

        Args:
            match: CandlestickMatch containing pattern name and calculated ratios.

        Returns:
            Decimal quality bonus between 0.00 and 0.03.
        """
        name = match.pattern_name
        bonus = _DECIMAL_ZERO

        # 1. Pinbar / Hammer / Shooting Star: wick dominance
        if name in ("bullish_pinbar", "bearish_pinbar"):
            if match.wick_ratio >= Decimal("0.75"):
                bonus += Decimal("0.03")
        # 2. Doji: long wick rejection
        elif name in ("dragonfly_doji", "gravestone_doji"):
            if match.wick_ratio >= Decimal("0.80"):
                bonus += Decimal("0.02")
        # 3. Engulfing: overwhelming body size
        elif name in ("bullish_engulfing", "bearish_engulfing"):
            if match.pattern_ratio >= Decimal("1.50"):
                bonus += Decimal("0.03")
        # 4. Stars: deep penetration
        elif name in ("morning_star", "evening_star"):
            if match.pattern_ratio >= Decimal("0.70"):
                bonus += Decimal("0.03")
        # 5. Piercing line / Dark cloud cover: deep penetration
        elif name in ("piercing_line", "dark_cloud_cover"):
            if match.pattern_ratio >= Decimal("0.70"):
                bonus += Decimal("0.03")
        # 6. Tweezers: extreme level alignment (wick_ratio is diff_pct <= 0.0003)
        elif name in ("tweezer_bottom", "tweezer_top"):
            if match.wick_ratio <= Decimal("0.0003") or match.pattern_ratio >= Decimal(
                "0.9997"
            ):
                bonus += Decimal("0.02")
        # 7. Marubozu: pure momentum body
        elif name in ("bullish_marubozu", "bearish_marubozu"):
            if match.body_ratio >= Decimal("0.92"):
                bonus += Decimal("0.03")

        return bonus

    def _score_patterns(
        self,
        matches: Sequence[CandlestickMatch],
    ) -> tuple[CandlestickMatch, Decimal]:
        """Score detected candlestick matches and calculate aggregate setup confidence.

        Note:
            Confidence is an uncalibrated heuristic setup score indicating
            structural clarity and technical alignment, not a calibrated
            statistical win probability.

        Args:
            matches: Sequence of non-conflicting directional CandlestickMatches.

        Returns:
            Tuple of (primary_candlestick_match, final_confidence).
        """
        scored: list[tuple[CandlestickMatch, Decimal, Decimal]] = []
        for m in matches:
            if m.pattern_name in _TRIPLE_PATTERNS:
                base = Decimal("0.85")
            elif m.pattern_name in _DUAL_PATTERNS:
                base = Decimal("0.80")
            elif m.pattern_name in _HARAMI_PATTERNS:
                base = Decimal("0.75")
            elif m.pattern_name in _SINGLE_PATTERNS:
                base = Decimal("0.70")
            else:
                base = Decimal("0.65")

            quality = self._pattern_quality_bonus(m)
            scored.append((m, base, quality))

        scored.sort(key=lambda item: item[1] + item[2], reverse=True)
        best_match, best_base, best_quality = scored[0]
        primary_confidence = best_base + best_quality

        # Multi-pattern confluence bonus:
        # All candlestick patterns evaluated at the current closed candle (C0)
        # share the final candle and its immediate sub-window (e.g., TRIPLE
        # C-2..C0 with DUAL C-1..C0, or DUAL C-1..C0 with SINGLE C0).
        # These represent correlated confirmation evidence (+0.01 per pattern)
        # rather than fully independent structural evidence (+0.05).
        # Total confluence bonus is strictly capped at _MAX_CONFLUENCE_BONUS (0.06).
        confluence_bonus = _DECIMAL_ZERO
        for _ in scored[1:]:
            confluence_bonus += Decimal("0.01")

        bounded_confluence = min(confluence_bonus, _MAX_CONFLUENCE_BONUS)
        final_conf = min(
            primary_confidence + bounded_confluence,
            _DECIMAL_MAX_CONFIDENCE,
        )
        return best_match, final_conf

    def calculate_exits(
        self,
        *,
        signal_type: SignalType,
        current_price: Decimal,
        rejection_level: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Calculate bounded Stop Loss and Take Profit levels.

        Separates structural invalidation level, fallback risk distance,
        and clamped minimum/maximum risk boundaries.

        Args:
            signal_type: BUY or SELL signal.
            current_price: Evaluated closed entry price.
            rejection_level: Geometric structural invalidation level from pattern.

        Returns:
            Tuple of (stop_loss_price, take_profit_price).
        """
        if not current_price.is_finite() or current_price <= _DECIMAL_ZERO:
            raise ValueError(
                f"Invalid current price for exit calculation: {current_price}"
            )

        is_rejection_valid = (
            rejection_level.is_finite() and rejection_level > _DECIMAL_ZERO
        )

        if signal_type is SignalType.BUY:
            # Structural rejection must be strictly below entry price for BUY
            if not is_rejection_valid or rejection_level >= current_price:
                sl_distance = current_price * self.fallback_sl_pct
                sl_price = current_price - sl_distance
            else:
                sl_distance = current_price - rejection_level
                sl_pct = sl_distance / current_price
                if sl_pct > self.max_sl_pct:
                    sl_price = current_price * (_DECIMAL_ONE - self.max_sl_pct)
                elif sl_pct < self.min_sl_pct:
                    sl_price = current_price * (_DECIMAL_ONE - self.min_sl_pct)
                else:
                    sl_price = rejection_level

            actual_sl_dist = current_price - sl_price
            tp_price = current_price + (self.risk_reward_ratio * actual_sl_dist)
            return sl_price, tp_price

        # SELL
        # Structural rejection must be strictly above entry price for SELL
        if not is_rejection_valid or rejection_level <= current_price:
            sl_distance = current_price * self.fallback_sl_pct
            sl_price = current_price + sl_distance
        else:
            sl_distance = rejection_level - current_price
            sl_pct = sl_distance / current_price
            if sl_pct > self.max_sl_pct:
                sl_price = current_price * (_DECIMAL_ONE + self.max_sl_pct)
            elif sl_pct < self.min_sl_pct:
                sl_price = current_price * (_DECIMAL_ONE + self.min_sl_pct)
            else:
                sl_price = rejection_level

        actual_sl_dist = sl_price - current_price
        tp_price = current_price - (self.risk_reward_ratio * actual_sl_dist)
        return sl_price, tp_price

    def _apply_ta_filters(
        self,
        *,
        signal: Signal,
        candles: Sequence[Candle],
    ) -> Signal:
        """Apply Technical Analysis filters (EMA trend, volume, RSI, BB, MACD, PSAR)."""
        ta_confidence_bonus = _DECIMAL_ZERO

        # 1. Trend Filter
        if self.use_trend_filter and len(candles) >= self.trend_ema_period:
            closes = tuple(c.close_price for c in candles)
            ema_series = calculate_ema(closes, period=self.trend_ema_period)
            trend_ema = ema_series[-1]
            if signal.signal_type == SignalType.BUY and signal.price < trend_ema:
                return Signal(
                    symbol=signal.symbol,
                    signal_type=SignalType.HOLD,
                    price=signal.price,
                    confidence=_DECIMAL_ZERO,
                    strategy_name=self.strategy_type.value,
                    generated_at=signal.generated_at,
                    stop_loss=None,
                    take_profit=None,
                    reason=(
                        f"Trend filter: Counter-trend BUY below EMA "
                        f"{self.trend_ema_period} ({trend_ema:.2f})"
                    ),
                )
            if signal.signal_type == SignalType.SELL and signal.price > trend_ema:
                return Signal(
                    symbol=signal.symbol,
                    signal_type=SignalType.HOLD,
                    price=signal.price,
                    confidence=_DECIMAL_ZERO,
                    strategy_name=self.strategy_type.value,
                    generated_at=signal.generated_at,
                    stop_loss=None,
                    take_profit=None,
                    reason=(
                        f"Trend filter: Counter-trend SELL above EMA "
                        f"{self.trend_ema_period} ({trend_ema:.2f})"
                    ),
                )
            if (
                signal.signal_type == SignalType.BUY
                and signal.price >= trend_ema * Decimal("1.005")
            ) or (
                signal.signal_type == SignalType.SELL
                and signal.price <= trend_ema * Decimal("0.995")
            ):
                ta_confidence_bonus += Decimal("0.02")

        # 2. Volume Filter
        if self.use_volume_filter and len(candles) >= self.volume_period + 1:
            baseline_vols = [c.volume for c in candles[-(self.volume_period + 1) : -1]]
            avg_vol = sum(baseline_vols, _DECIMAL_ZERO) / Decimal(
                str(len(baseline_vols))
            )
            current_vol = candles[-1].volume

            if avg_vol <= _DECIMAL_ZERO or not avg_vol.is_finite():
                return Signal(
                    symbol=signal.symbol,
                    signal_type=SignalType.HOLD,
                    price=signal.price,
                    confidence=_DECIMAL_ZERO,
                    strategy_name=self.strategy_type.value,
                    generated_at=signal.generated_at,
                    stop_loss=None,
                    take_profit=None,
                    reason="Volume filter: baseline volume average is zero or invalid",
                )

            threshold_vol = avg_vol * self.volume_multiplier
            if current_vol < threshold_vol:
                return Signal(
                    symbol=signal.symbol,
                    signal_type=SignalType.HOLD,
                    price=signal.price,
                    confidence=_DECIMAL_ZERO,
                    strategy_name=self.strategy_type.value,
                    generated_at=signal.generated_at,
                    stop_loss=None,
                    take_profit=None,
                    reason=(
                        f"Volume {current_vol:.2f} below required SMA threshold "
                        f"{threshold_vol:.2f}"
                    ),
                )
            if current_vol >= avg_vol * Decimal("1.5"):
                ta_confidence_bonus += Decimal("0.03")

        # 3. RSI Momentum Filter
        if self.use_rsi_filter and len(candles) >= self.rsi_period + 1:
            closes = tuple(c.close_price for c in candles)
            rsi_series = calculate_rsi(closes, period=self.rsi_period)
            current_rsi = rsi_series[-1]
            if signal.signal_type == SignalType.BUY:
                if current_rsi > self.rsi_long_max:
                    return Signal(
                        symbol=signal.symbol,
                        signal_type=SignalType.HOLD,
                        price=signal.price,
                        confidence=_DECIMAL_ZERO,
                        strategy_name=self.strategy_type.value,
                        generated_at=signal.generated_at,
                        stop_loss=None,
                        take_profit=None,
                        reason=(
                            f"RSI {current_rsi:.2f} above long ceiling "
                            f"{self.rsi_long_max:.2f}"
                        ),
                    )
                if self.require_rsi_direction and len(rsi_series) >= 2:
                    prev_rsi = rsi_series[-2]
                    if current_rsi <= prev_rsi:
                        return Signal(
                            symbol=signal.symbol,
                            signal_type=SignalType.HOLD,
                            price=signal.price,
                            confidence=_DECIMAL_ZERO,
                            strategy_name=self.strategy_type.value,
                            generated_at=signal.generated_at,
                            stop_loss=None,
                            take_profit=None,
                            reason=(
                                f"RSI declining ({current_rsi:.2f} <= {prev_rsi:.2f}), "
                                f"requiring rising RSI for BUY"
                            ),
                        )
                if current_rsi <= _RSI_OVERSOLD_BONUS_THRESHOLD:
                    ta_confidence_bonus += Decimal("0.02")
            elif signal.signal_type == SignalType.SELL:
                if current_rsi < self.rsi_short_min:
                    return Signal(
                        symbol=signal.symbol,
                        signal_type=SignalType.HOLD,
                        price=signal.price,
                        confidence=_DECIMAL_ZERO,
                        strategy_name=self.strategy_type.value,
                        generated_at=signal.generated_at,
                        stop_loss=None,
                        take_profit=None,
                        reason=(
                            f"RSI {current_rsi:.2f} below short floor "
                            f"{self.rsi_short_min:.2f}"
                        ),
                    )
                if self.require_rsi_direction and len(rsi_series) >= 2:
                    prev_rsi = rsi_series[-2]
                    if current_rsi >= prev_rsi:
                        return Signal(
                            symbol=signal.symbol,
                            signal_type=SignalType.HOLD,
                            price=signal.price,
                            confidence=_DECIMAL_ZERO,
                            strategy_name=self.strategy_type.value,
                            generated_at=signal.generated_at,
                            stop_loss=None,
                            take_profit=None,
                            reason=(
                                f"RSI rising ({current_rsi:.2f} >= {prev_rsi:.2f}), "
                                f"requiring falling RSI for SELL"
                            ),
                        )
                if current_rsi >= _RSI_OVERBOUGHT_BONUS_THRESHOLD:
                    ta_confidence_bonus += Decimal("0.02")

        # 4. Bollinger Bands Touch & Rejection Filter
        if self.use_bb_filter and len(candles) >= self.bb_period:
            closes = tuple(c.close_price for c in candles)
            bb_res = calculate_bollinger_bands(
                closes,
                period=self.bb_period,
                standard_deviation=self.bb_std_dev,
            )
            current_upper_bb = bb_res.upper[-1]
            current_lower_bb = bb_res.lower[-1]
            curr_candle = candles[-1]
            prev_candle = candles[-2] if len(candles) >= 2 else curr_candle
            prev_upper_bb = (
                bb_res.upper[-2] if len(bb_res.upper) >= 2 else current_upper_bb
            )
            prev_lower_bb = (
                bb_res.lower[-2] if len(bb_res.lower) >= 2 else current_lower_bb
            )

            if signal.signal_type == SignalType.SELL:
                # Candle must touch Upper BB (current or prev) and reject below
                touched_upper_bb = (
                    curr_candle.high_price >= current_upper_bb
                    or prev_candle.high_price >= prev_upper_bb
                )
                rejected_below_upper = curr_candle.close_price < current_upper_bb

                if not touched_upper_bb:
                    return Signal(
                        symbol=signal.symbol,
                        signal_type=SignalType.HOLD,
                        price=signal.price,
                        confidence=_DECIMAL_ZERO,
                        strategy_name=self.strategy_type.value,
                        generated_at=signal.generated_at,
                        stop_loss=None,
                        take_profit=None,
                        reason=(
                            f"BB filter: SELL high {curr_candle.high_price:.2f} "
                            f"did not touch Upper BB ({current_upper_bb:.2f})"
                        ),
                    )

                if not rejected_below_upper:
                    return Signal(
                        symbol=signal.symbol,
                        signal_type=SignalType.HOLD,
                        price=signal.price,
                        confidence=_DECIMAL_ZERO,
                        strategy_name=self.strategy_type.value,
                        generated_at=signal.generated_at,
                        stop_loss=None,
                        take_profit=None,
                        reason=(
                            f"BB filter: SELL close {curr_candle.close_price:.2f} "
                            f"closed above Upper BB ({current_upper_bb:.2f}), "
                            f"requiring price rejection back below Upper BB"
                        ),
                    )
                ta_confidence_bonus += Decimal("0.02")

            elif signal.signal_type == SignalType.BUY:
                # Candle menyentuh BB Lower lalu memantul kembali ke atas
                touched_lower_bb = (
                    curr_candle.low_price <= current_lower_bb
                    or prev_candle.low_price <= prev_lower_bb
                )
                bounced_above_lower = curr_candle.close_price > current_lower_bb

                if not touched_lower_bb:
                    return Signal(
                        symbol=signal.symbol,
                        signal_type=SignalType.HOLD,
                        price=signal.price,
                        confidence=_DECIMAL_ZERO,
                        strategy_name=self.strategy_type.value,
                        generated_at=signal.generated_at,
                        stop_loss=None,
                        take_profit=None,
                        reason=(
                            f"BB filter: BUY low {curr_candle.low_price:.2f} "
                            f"did not touch Lower BB ({current_lower_bb:.2f})"
                        ),
                    )

                if not bounced_above_lower:
                    return Signal(
                        symbol=signal.symbol,
                        signal_type=SignalType.HOLD,
                        price=signal.price,
                        confidence=_DECIMAL_ZERO,
                        strategy_name=self.strategy_type.value,
                        generated_at=signal.generated_at,
                        stop_loss=None,
                        take_profit=None,
                        reason=(
                            f"BB filter: BUY close {curr_candle.close_price:.2f} "
                            f"closed below Lower BB ({current_lower_bb:.2f}), "
                            f"requiring price bounce back above Lower BB"
                        ),
                    )
                ta_confidence_bonus += Decimal("0.02")

        # 5. MACD Momentum Filter
        min_macd_candles = self.macd_slow_period + self.macd_signal_period
        if self.use_macd_filter and len(candles) >= min_macd_candles:
            closes = tuple(c.close_price for c in candles)
            macd_res = calculate_macd(
                closes,
                fast_period=self.macd_fast_period,
                slow_period=self.macd_slow_period,
                signal_period=self.macd_signal_period,
            )
            if len(macd_res.macd) >= 2 and len(macd_res.histogram) >= 2:
                current_macd = macd_res.macd[-1]
                prev_macd = macd_res.macd[-2]
                curr_hist = macd_res.histogram[-1]
                prev_hist = macd_res.histogram[-2]

                if signal.signal_type == SignalType.SELL:
                    # MACD must show downward slope
                    if current_macd >= prev_macd:
                        return Signal(
                            symbol=signal.symbol,
                            signal_type=SignalType.HOLD,
                            price=signal.price,
                            confidence=_DECIMAL_ZERO,
                            strategy_name=self.strategy_type.value,
                            generated_at=signal.generated_at,
                            stop_loss=None,
                            take_profit=None,
                            reason=(
                                "MACD filter: SELL rejected because MACD is not "
                                f"declining ({current_macd:.4f} >= {prev_macd:.4f})"
                            ),
                        )
                    if curr_hist < _DECIMAL_ZERO and curr_hist < prev_hist:
                        ta_confidence_bonus += Decimal("0.02")

                elif signal.signal_type == SignalType.BUY:
                    # MACD must show upward slope
                    if current_macd <= prev_macd:
                        return Signal(
                            symbol=signal.symbol,
                            signal_type=SignalType.HOLD,
                            price=signal.price,
                            confidence=_DECIMAL_ZERO,
                            strategy_name=self.strategy_type.value,
                            generated_at=signal.generated_at,
                            stop_loss=None,
                            take_profit=None,
                            reason=(
                                f"MACD filter: BUY rejected because MACD is not rising "
                                f"({current_macd:.4f} <= {prev_macd:.4f})"
                            ),
                        )
                    if curr_hist > _DECIMAL_ZERO and curr_hist > prev_hist:
                        ta_confidence_bonus += Decimal("0.02")

        # 6. Parabolic SAR Filter (Pendekatan 2: Proximity Tolerance)
        if self.use_psar_filter and len(candles) >= 2:
            highs = tuple(c.high_price for c in candles)
            lows = tuple(c.low_price for c in candles)
            psar_res = calculate_psar(highs, lows)
            current_sar = psar_res.values[-1]

            if signal.signal_type == SignalType.BUY:
                if signal.price < current_sar:
                    dist_pct = (current_sar - signal.price) / signal.price
                    if dist_pct > self.psar_max_proximity_pct:
                        return Signal(
                            symbol=signal.symbol,
                            signal_type=SignalType.HOLD,
                            price=signal.price,
                            confidence=_DECIMAL_ZERO,
                            strategy_name=self.strategy_type.value,
                            generated_at=signal.generated_at,
                            stop_loss=None,
                            take_profit=None,
                            reason=(
                                f"PSAR filter: BUY price {signal.price:.2f} too far "
                                f"below SAR ({current_sar:.2f}, "
                                f"dist={dist_pct * 100:.2f}% > "
                                f"{self.psar_max_proximity_pct * 100:.2f}%)"
                            ),
                        )
                else:
                    ta_confidence_bonus += Decimal("0.02")

            elif signal.signal_type == SignalType.SELL:
                if signal.price > current_sar:
                    dist_pct = (signal.price - current_sar) / signal.price
                    if dist_pct > self.psar_max_proximity_pct:
                        return Signal(
                            symbol=signal.symbol,
                            signal_type=SignalType.HOLD,
                            price=signal.price,
                            confidence=_DECIMAL_ZERO,
                            strategy_name=self.strategy_type.value,
                            generated_at=signal.generated_at,
                            stop_loss=None,
                            take_profit=None,
                            reason=(
                                f"PSAR filter: SELL price {signal.price:.2f} too far "
                                f"above SAR ({current_sar:.2f}, "
                                f"dist={dist_pct * 100:.2f}% > "
                                f"{self.psar_max_proximity_pct * 100:.2f}%)"
                            ),
                        )
                else:
                    ta_confidence_bonus += Decimal("0.02")

        if ta_confidence_bonus > _DECIMAL_ZERO:
            bounded_bonus = min(ta_confidence_bonus, _MAX_TA_BONUS)
            new_confidence = min(
                signal.confidence + bounded_bonus,
                _DECIMAL_MAX_CONFIDENCE,
            )
            return replace(signal, confidence=new_confidence)

        return signal
