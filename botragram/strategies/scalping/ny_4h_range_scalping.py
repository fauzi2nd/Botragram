"""
Botragram

Description:
    Production-ready New York 4-Hour Range Scalping strategy. Anchors to the
    first closed 4-Hour candle of the New York trading session (00:00 - 04:00
    EST/EDT) and evaluates 5-minute candle breakout and re-entry confirmations.

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
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import SignalType, StrategyType
from botragram.indicators import calculate_ema, calculate_rsi
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "NY4HRangeScalpingStrategy",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Decimal = Decimal("0")
_DECIMAL_ONE: Decimal = Decimal("1")
_DECIMAL_TWO: Decimal = Decimal("2")
_DECIMAL_ONE_HUNDRED: Decimal = Decimal("100")

_NY_TZ: ZoneInfo = ZoneInfo("America/New_York")
_INITIAL_RANGE_START_HOUR: int = 0
_INITIAL_RANGE_END_HOUR: int = 4
_DEFAULT_MINIMUM_CANDLES: int = 50


# =============================================================================
# Strategy Class
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class NY4HRangeScalpingStrategy(BaseStrategy):
    """Scalping strategy anchoring to the New York initial 4-Hour range."""

    # Risk-Reward and Setup Parameters
    risk_reward_ratio: Decimal = Decimal("0.8")
    max_breakout_bars: int = 12
    max_sl_pct: Decimal = Decimal("0.03")
    min_sl_pct: Decimal = Decimal("0.015")
    fallback_sl_pct: Decimal = Decimal("0.015")
    base_confidence: Decimal = Decimal("0.70")
    min_confidence: Decimal = Decimal("0.75")

    # Volume Confirmation Parameters
    use_volume_filter: bool = True
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.0")
    volume_confidence_bonus: Decimal = Decimal("0.10")
    require_volume_confirmation: bool = False

    # Trend Filter Parameters
    require_trend_filter: bool = False
    trend_ema_period: int = 50

    # RSI Filter Parameters
    use_rsi_filter: bool = True
    rsi_period: int = 14
    rsi_long_max: Decimal = Decimal("54.0")
    rsi_short_min: Decimal = Decimal("44.0")

    # Open Interest Confluence
    use_open_interest: bool = False
    min_oi_change_pct: Decimal = Decimal("0.0")
    oi_confidence_bonus: Decimal = Decimal("0.05")
    require_oi_confluence: bool = False

    def __post_init__(self) -> None:
        """Validate strategy parameter invariants."""
        if self.risk_reward_ratio <= _DECIMAL_ZERO:
            raise ValueError("risk_reward_ratio must be positive")

        if self.max_breakout_bars <= 0:
            raise ValueError("max_breakout_bars must be greater than zero")

        if self.max_sl_pct <= _DECIMAL_ZERO:
            raise ValueError("max_sl_pct must be positive")

        if self.min_sl_pct < _DECIMAL_ZERO:
            raise ValueError("min_sl_pct must not be negative")

        if self.min_sl_pct > self.max_sl_pct:
            raise ValueError("min_sl_pct cannot exceed max_sl_pct")

        if self.fallback_sl_pct <= _DECIMAL_ZERO:
            raise ValueError("fallback_sl_pct must be positive")

        if not (_DECIMAL_ZERO <= self.min_confidence <= _DECIMAL_ONE):
            raise ValueError("min_confidence must be between 0.0 and 1.0")

        if not (_DECIMAL_ZERO <= self.base_confidence <= _DECIMAL_ONE):
            raise ValueError("base_confidence must be between 0.0 and 1.0")

        if self.volume_period <= 0:
            raise ValueError("volume_period must be greater than zero")

        if self.volume_multiplier < _DECIMAL_ZERO:
            raise ValueError("volume_multiplier must not be negative")

        if self.volume_confidence_bonus < _DECIMAL_ZERO:
            raise ValueError("volume_confidence_bonus must not be negative")

        if self.trend_ema_period <= 0:
            raise ValueError("trend_ema_period must be greater than zero")

        if self.rsi_period <= 0:
            raise ValueError("rsi_period must be greater than zero")

        if not (_DECIMAL_ZERO <= self.rsi_long_max <= _DECIMAL_ONE_HUNDRED):
            raise ValueError("rsi_long_max must be between 0.0 and 100.0")

        if not (_DECIMAL_ZERO <= self.rsi_short_min <= _DECIMAL_ONE_HUNDRED):
            raise ValueError("rsi_short_min must be between 0.0 and 100.0")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type enumeration."""
        return StrategyType.NY_4H_RANGE_SCALPING

    @property
    def minimum_candles(self) -> int:
        """Return minimum candle count required for evaluation."""
        return max(
            _DEFAULT_MINIMUM_CANDLES,
            self.volume_period + 5,
            self.trend_ema_period + 5 if self.require_trend_filter else 0,
            self.rsi_period + 5 if self.use_rsi_filter else 0,
        )

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a trading signal from ordered 5M candle data.

        Args:
            candles: Ordered sequence of 5M candles.

        Returns:
            Generated trading signal (BUY, SELL, or HOLD).
        """
        self.validate_candles(candles=candles)

        latest_candle = candles[-1]
        latest_ny_time = latest_candle.open_time.astimezone(_NY_TZ)
        current_day: date = latest_ny_time.date()

        # Isolate candles for the active New York trading day
        day_candles: list[Candle] = [
            candle
            for candle in candles
            if candle.open_time.astimezone(_NY_TZ).date() == current_day
        ]

        # First 4H window constituent candles (00:00:00 to 03:59:59 NY)
        initial_4h_candles: list[Candle] = [
            candle
            for candle in day_candles
            if candle.open_time.astimezone(_NY_TZ).hour < _INITIAL_RANGE_END_HOUR
        ]

        # The 4H candle is only closed once NY time reaches 04:00:00+
        if latest_ny_time.hour < _INITIAL_RANGE_END_HOUR or not initial_4h_candles:
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
                    "NY 4H initial range forming "
                    f"(current NY time: {latest_ny_time.strftime('%H:%M')})"
                ),
            )

        range_high: Decimal = max(c.high_price for c in initial_4h_candles)
        range_low: Decimal = min(c.low_price for c in initial_4h_candles)

        # Active evaluation window after the 4H range is closed (04:00:00+ NY)
        active_candles: list[Candle] = [
            candle
            for candle in day_candles
            if candle.open_time.astimezone(_NY_TZ).hour >= _INITIAL_RANGE_END_HOUR
        ]

        if len(active_candles) < 2:
            return Signal(
                symbol=latest_candle.symbol,
                signal_type=SignalType.HOLD,
                price=latest_candle.close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=latest_candle.close_time,
                stop_loss=None,
                take_profit=None,
                reason="Waiting for post-4H 5M confirmation bars",
            )

        current = active_candles[-1]
        preceding_candles = active_candles[:-1]

        # ---------------------------------------------------------------------
        # Short Setup: Breakout above Range_High, then re-entry below Range_High
        # ---------------------------------------------------------------------
        if current.close_price < range_high:
            breakout_run_short: list[Candle] = []
            for candle in reversed(preceding_candles):
                if candle.close_price > range_high:
                    breakout_run_short.append(candle)
                else:
                    break

            if 1 <= len(breakout_run_short) <= self.max_breakout_bars:
                # Re-entry confirmed on current candle close
                swing_high = max(
                    max(c.high_price for c in breakout_run_short),
                    current.high_price,
                )

                if swing_high <= current.close_price:
                    sl_price = current.close_price * (
                        _DECIMAL_ONE + self.fallback_sl_pct
                    )
                else:
                    sl_distance = swing_high - current.close_price
                    sl_pct = sl_distance / current.close_price
                    if sl_pct > self.max_sl_pct:
                        sl_price = current.close_price * (
                            _DECIMAL_ONE + self.max_sl_pct
                        )
                    elif sl_pct < self.min_sl_pct:
                        sl_price = current.close_price * (
                            _DECIMAL_ONE + self.min_sl_pct
                        )
                    else:
                        sl_price = swing_high

                actual_sl_dist = sl_price - current.close_price
                tp_price = current.close_price - (
                    self.risk_reward_ratio * actual_sl_dist
                )

                signal = Signal(
                    symbol=current.symbol,
                    signal_type=SignalType.SELL,
                    price=current.close_price,
                    confidence=self.base_confidence,
                    strategy_name=self.strategy_type.value,
                    generated_at=current.close_time,
                    stop_loss=sl_price,
                    take_profit=tp_price,
                    reason=(
                        f"NY 4H Short: {len(breakout_run_short)} bar breakout "
                        f"above {range_high}, re-entry at {current.close_price}"
                    ),
                )
                return self._finalize_signal(signal=signal, candles=candles)

        # ---------------------------------------------------------------------
        # Long Setup: Breakout below Range_Low, then re-entry above Range_Low
        # ---------------------------------------------------------------------
        if current.close_price > range_low:
            breakout_run_long: list[Candle] = []
            for candle in reversed(preceding_candles):
                if candle.close_price < range_low:
                    breakout_run_long.append(candle)
                else:
                    break

            if 1 <= len(breakout_run_long) <= self.max_breakout_bars:
                # Re-entry confirmed on current candle close
                swing_low = min(
                    min(c.low_price for c in breakout_run_long),
                    current.low_price,
                )

                if swing_low >= current.close_price:
                    sl_price = current.close_price * (
                        _DECIMAL_ONE - self.fallback_sl_pct
                    )
                else:
                    sl_distance = current.close_price - swing_low
                    sl_pct = sl_distance / current.close_price
                    if sl_pct > self.max_sl_pct:
                        sl_price = current.close_price * (
                            _DECIMAL_ONE - self.max_sl_pct
                        )
                    elif sl_pct < self.min_sl_pct:
                        sl_price = current.close_price * (
                            _DECIMAL_ONE - self.min_sl_pct
                        )
                    else:
                        sl_price = swing_low

                actual_sl_dist = current.close_price - sl_price
                tp_price = current.close_price + (
                    self.risk_reward_ratio * actual_sl_dist
                )

                signal = Signal(
                    symbol=current.symbol,
                    signal_type=SignalType.BUY,
                    price=current.close_price,
                    confidence=self.base_confidence,
                    strategy_name=self.strategy_type.value,
                    generated_at=current.close_time,
                    stop_loss=sl_price,
                    take_profit=tp_price,
                    reason=(
                        f"NY 4H Long: {len(breakout_run_long)} bar breakout "
                        f"below {range_low}, re-entry at {current.close_price}"
                    ),
                )
                return self._finalize_signal(signal=signal, candles=candles)

        # ---------------------------------------------------------------------
        # Neutral / In-Range: No active re-entry on the current candle
        # ---------------------------------------------------------------------
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
                f"Within NY 4H range [{range_low}, {range_high}], no active re-entry"
            ),
        )

    def _finalize_signal(
        self,
        *,
        signal: Signal,
        candles: Sequence[Candle],
    ) -> Signal:
        """Apply volume, trend filter, Open Interest, and confidence gating."""
        if signal.signal_type == SignalType.HOLD:
            return signal

        current_confidence = signal.confidence

        # 1. Volume Confirmation on re-entry candle
        if self.use_volume_filter and len(candles) >= self.volume_period + 1:
            recent_vols = tuple(c.volume for c in candles[-self.volume_period - 1 : -1])
            if recent_vols:
                avg_vol = sum(recent_vols) / Decimal(str(len(recent_vols)))
                current_vol = candles[-1].volume
                if current_vol >= avg_vol * self.volume_multiplier:
                    current_confidence = min(
                        _DECIMAL_ONE,
                        current_confidence + self.volume_confidence_bonus,
                    )
                elif self.require_volume_confirmation:
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
                            f"Volume {current_vol} below required SMA threshold "
                            f"{avg_vol * self.volume_multiplier:.2f}"
                        ),
                    )

        # 2. Trend Filter (optional EMA alignment)
        if self.require_trend_filter and len(candles) >= self.trend_ema_period:
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
                        f"Counter-trend BUY below EMA "
                        f"{self.trend_ema_period} ({trend_ema})"
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
                        f"Counter-trend SELL above EMA "
                        f"{self.trend_ema_period} ({trend_ema})"
                    ),
                )

        # 3. RSI Filter (momentum/exhaustion confirmation)
        if self.use_rsi_filter and len(candles) >= self.rsi_period + 1:
            closes = tuple(c.close_price for c in candles)
            rsi_series = calculate_rsi(closes, period=self.rsi_period)
            current_rsi = rsi_series[-1]
            if signal.signal_type == SignalType.BUY and current_rsi > self.rsi_long_max:
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
            if (
                signal.signal_type == SignalType.SELL
                and current_rsi < self.rsi_short_min
            ):
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

        updated_signal = Signal(
            symbol=signal.symbol,
            signal_type=signal.signal_type,
            price=signal.price,
            confidence=current_confidence,
            strategy_name=signal.strategy_name,
            generated_at=signal.generated_at,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=signal.reason,
        )

        # 3. Open Interest Confluence (if enabled)
        if self.use_open_interest:
            updated_signal = self.apply_open_interest_confluence(
                signal=updated_signal,
                candles=candles,
                min_change_pct=self.min_oi_change_pct,
                confidence_bonus=self.oi_confidence_bonus,
                strict=self.require_oi_confluence,
            )

        # 4. Confidence Threshold Gate
        if updated_signal.confidence < self.min_confidence:
            return Signal(
                symbol=updated_signal.symbol,
                signal_type=SignalType.HOLD,
                price=updated_signal.price,
                confidence=_DECIMAL_ZERO,
                strategy_name=self.strategy_type.value,
                generated_at=updated_signal.generated_at,
                stop_loss=None,
                take_profit=None,
                reason=(
                    f"Confidence {updated_signal.confidence} below threshold "
                    f"{self.min_confidence}"
                ),
            )

        return updated_signal
