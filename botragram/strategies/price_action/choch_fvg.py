"""
Botragram

Description:
    Smart Money Concepts (SMC) CHoCH (Change of Character) and
    Fair Value Gap (FVG) price action strategy.

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
from botragram.indicators.price_action import calculate_choch_fvg
from botragram.indicators.trend.ema import calculate_ema
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "ChochFvgStrategy",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# Strategy Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class ChochFvgStrategy(BaseStrategy):
    """Generate signals from Smart Money Concepts CHoCH and FVG mitigations."""

    swing_window: int = 5
    fvg_lookback: int = 20
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.2")
    min_body_ratio: Decimal = Decimal("0.50")
    trend_period: int = 50
    require_trend_filter: bool = True

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if self.swing_window <= 0:
            raise ValueError("CHoCH swing window must be greater than zero")

        if self.fvg_lookback <= 0:
            raise ValueError("FVG lookback must be greater than zero")

        if self.volume_period <= 0:
            raise ValueError("Volume period must be greater than zero")

        if self.volume_multiplier <= _DECIMAL_ZERO:
            raise ValueError("Volume multiplier must be greater than zero")

        if self.min_body_ratio <= _DECIMAL_ZERO:
            raise ValueError("Minimum body ratio must be greater than zero")

        if self.trend_period <= 0:
            raise ValueError("Trend period must be greater than zero")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.CHOCH_FVG

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required for evaluation."""
        return max(self.swing_window * 2 + 1, self.volume_period + 1)

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a trading signal from CHoCH structure shifts and FVG retests."""
        self.validate_candles(candles=candles)

        high_prices = tuple(candle.high_price for candle in candles)
        low_prices = tuple(candle.low_price for candle in candles)
        close_prices = tuple(candle.close_price for candle in candles)
        open_prices = tuple(candle.open_price for candle in candles)
        volumes = tuple(candle.volume for candle in candles)

        result = calculate_choch_fvg(
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
        )

        signal_type, reason = self._resolve_signal(
            result=result,
            close_prices=close_prices,
        )
        latest_candle = candles[-1]

        confidence = (
            result.confidence if signal_type is not SignalType.HOLD else _DECIMAL_ZERO
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

    def _resolve_signal(
        self,
        *,
        result: object,
        close_prices: Sequence[Decimal],
    ) -> tuple[SignalType, str]:
        """Resolve signal type and rationale from CHoCH and FVG confluence."""
        from botragram.indicators.price_action import ChochFvgResult

        if not isinstance(result, ChochFvgResult):
            return SignalType.HOLD, "Invalid CHoCH calculation result"

        trend_ok_for_buy = True
        trend_ok_for_sell = True
        if self.require_trend_filter and len(close_prices) >= self.trend_period:
            trend_ema = calculate_ema(close_prices, period=self.trend_period)[-1]
            latest_close = close_prices[-1]
            trend_ok_for_buy = latest_close >= trend_ema
            trend_ok_for_sell = latest_close <= trend_ema

        if result.retesting_bullish_fvg:
            if not trend_ok_for_buy:
                return (
                    SignalType.HOLD,
                    "Bullish FVG retest rejected: below trend EMA",
                )
            sweep_note = " with liquidity sweep" if result.liquidity_swept else ""
            return (
                SignalType.BUY,
                f"Bullish CHoCH structure shift{sweep_note} and confirmed FVG retest",
            )

        if result.retesting_bearish_fvg:
            if not trend_ok_for_sell:
                return (
                    SignalType.HOLD,
                    "Bearish FVG retest rejected: above trend EMA",
                )
            sweep_note = " with liquidity sweep" if result.liquidity_swept else ""
            return (
                SignalType.SELL,
                f"Bearish CHoCH structure shift{sweep_note} and confirmed FVG retest",
            )

        return (
            SignalType.HOLD,
            "No active CHoCH and FVG confluence",
        )
