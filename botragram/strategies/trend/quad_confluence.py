"""
Botragram

Description:
    Quad-Confluence strategy combining Stochastic RSI, Bollinger Bands,
    Parabolic SAR, and MACD.

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
    calculate_bollinger_bands,
    calculate_macd,
    calculate_psar,
    calculate_stoch_rsi,
)
from botragram.models import Candle, Signal
from botragram.strategies.base import BaseStrategy

__all__ = [
    "QuadConfluenceStrategy",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE = Decimal("1")
_DECIMAL_ONE_HUNDRED = Decimal("100")
_BASE_CONFIDENCE = Decimal("0.65")
_MAX_CONFIDENCE = Decimal("0.95")
_STOCH_WEIGHT = Decimal("0.15")
_MACD_WEIGHT = Decimal("0.15")
_STOCH_ZONE_BUFFER = Decimal("10.0")


# =============================================================================
# Strategy Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class QuadConfluenceStrategy(BaseStrategy):
    """Generate high-probability entries using 4-pillar technical confluence.

    Pillars:
    1. Trend & Trailing: Parabolic SAR (filters trade direction).
    2. Momentum: MACD (validates real buying/selling momentum).
    3. Volatility Envelope: Bollinger Bands (ensures sensible price boundaries).
    4. Timing Trigger: Stochastic RSI (%K crossing %D from oversold/overbought).
    """

    # Oscillator parameters
    rsi_period: int = 14
    stoch_period: int = 14
    k_period: int = 3
    d_period: int = 3
    stoch_oversold: Decimal = Decimal("20.0")
    stoch_overbought: Decimal = Decimal("80.0")

    # Bollinger Bands parameters
    bb_period: int = 20
    bb_std_dev: Decimal = Decimal("2.0")

    # Parabolic SAR parameters
    sar_step: Decimal = Decimal("0.02")
    sar_max_step: Decimal = Decimal("0.20")

    # MACD parameters
    macd_fast_period: int = 12
    macd_slow_period: int = 26
    macd_signal_period: int = 9

    def __post_init__(self) -> None:
        """Validate bounded strategy configuration."""
        if (
            self.rsi_period <= 0
            or self.stoch_period <= 0
            or self.k_period <= 0
            or self.d_period <= 0
        ):
            raise ValueError("Quad-Confluence oscillator periods must be positive")

        if not (
            _DECIMAL_ZERO
            <= self.stoch_oversold
            < self.stoch_overbought
            <= _DECIMAL_ONE_HUNDRED
        ):
            raise ValueError(
                "Stoch RSI thresholds must satisfy 0 <= oversold < overbought <= 100"
            )

        if self.bb_period <= 0 or self.bb_std_dev <= _DECIMAL_ZERO:
            raise ValueError("Bollinger Bands parameters must be positive")

        if self.sar_step <= _DECIMAL_ZERO or self.sar_max_step <= _DECIMAL_ZERO:
            raise ValueError("Parabolic SAR step parameters must be positive")

        if self.sar_step > self.sar_max_step:
            raise ValueError("Parabolic SAR step must not exceed maximum step")

        if (
            self.macd_fast_period <= 0
            or self.macd_slow_period <= 0
            or self.macd_signal_period <= 0
        ):
            raise ValueError("MACD periods must be positive")

        if self.macd_fast_period >= self.macd_slow_period:
            raise ValueError("MACD fast period must be less than slow period")

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""
        return StrategyType.QUAD_CONFLUENCE

    @property
    def minimum_candles(self) -> int:
        """Return the minimum candle count required."""
        stoch_req = self.rsi_period + self.stoch_period + self.k_period + self.d_period
        macd_req = self.macd_slow_period + self.macd_signal_period + 1
        bb_req = self.bb_period + 1
        return max(stoch_req, macd_req, bb_req)

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a validated Quad-Confluence signal."""
        self.validate_candles(candles=candles)

        high_prices = tuple(candle.high_price for candle in candles)
        low_prices = tuple(candle.low_price for candle in candles)
        close_prices = tuple(candle.close_price for candle in candles)

        stoch_res = calculate_stoch_rsi(
            close_prices,
            rsi_period=self.rsi_period,
            stoch_period=self.stoch_period,
            k_period=self.k_period,
            d_period=self.d_period,
        )

        bb_res = calculate_bollinger_bands(
            close_prices,
            period=self.bb_period,
            standard_deviation=self.bb_std_dev,
        )

        psar_res = calculate_psar(
            highs=high_prices,
            lows=low_prices,
            acceleration_step=self.sar_step,
            acceleration_maximum=self.sar_max_step,
        )

        macd_res = calculate_macd(
            close_prices,
            fast_period=self.macd_fast_period,
            slow_period=self.macd_slow_period,
            signal_period=self.macd_signal_period,
        )

        latest_candle = candles[-1]
        prev_k = stoch_res.k[-2]
        curr_k = stoch_res.k[-1]
        prev_d = stoch_res.d[-2]
        curr_d = stoch_res.d[-1]

        sar_is_bullish = psar_res.is_uptrend[-1]
        macd_histogram = macd_res.histogram[-1]
        macd_line = macd_res.macd[-1]
        macd_signal = macd_res.signal[-1]

        upper_band = bb_res.upper[-1]
        lower_band = bb_res.lower[-1]
        close_price = latest_candle.close_price

        signal_type, reason = self._resolve_signal(
            prev_k=prev_k,
            curr_k=curr_k,
            prev_d=prev_d,
            curr_d=curr_d,
            sar_is_bullish=sar_is_bullish,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            close_price=close_price,
            upper_band=upper_band,
            lower_band=lower_band,
        )

        confidence = self._calculate_confidence(
            signal_type=signal_type,
            curr_k=curr_k,
            curr_d=curr_d,
            macd_histogram=macd_histogram,
            close_price=close_price,
        )

        return Signal(
            symbol=latest_candle.symbol,
            signal_type=signal_type,
            price=close_price,
            confidence=confidence,
            strategy_name=self.strategy_type.value,
            generated_at=latest_candle.close_time,
            reason=reason,
        )

    def _resolve_signal(
        self,
        *,
        prev_k: Decimal,
        curr_k: Decimal,
        prev_d: Decimal,
        curr_d: Decimal,
        sar_is_bullish: bool,
        macd_line: Decimal,
        macd_signal: Decimal,
        macd_histogram: Decimal,
        close_price: Decimal,
        upper_band: Decimal,
        lower_band: Decimal,
    ) -> tuple[SignalType, str]:
        """Resolve entry trigger and 4-pillar state validation."""
        # 1. Timing trigger: Stoch RSI crossover
        bullish_stoch_cross = (
            prev_k <= prev_d
            and curr_k > curr_d
            and (
                prev_k <= self.stoch_oversold
                or curr_k <= self.stoch_oversold + _STOCH_ZONE_BUFFER
            )
        )
        bearish_stoch_cross = (
            prev_k >= prev_d
            and curr_k < curr_d
            and (
                prev_k >= self.stoch_overbought
                or curr_k >= self.stoch_overbought - _STOCH_ZONE_BUFFER
            )
        )

        # 2. Bullish Confluence
        if bullish_stoch_cross:
            if not sar_is_bullish:
                return (
                    SignalType.HOLD,
                    "Bullish Stoch RSI trigger rejected: Parabolic SAR is bearish",
                )
            if macd_line <= macd_signal or macd_histogram <= _DECIMAL_ZERO:
                return (
                    SignalType.HOLD,
                    "Bullish Stoch RSI trigger rejected: MACD momentum is not bullish",
                )
            if close_price >= upper_band:
                return (
                    SignalType.HOLD,
                    "Bullish Stoch RSI trigger rejected: Price extended at Upper Band",
                )
            return (
                SignalType.BUY,
                "Quad-Confluence BUY: Stoch RSI oversold crossover confirmed "
                "by SAR, MACD, and BB",
            )

        # 3. Bearish Confluence
        if bearish_stoch_cross:
            if sar_is_bullish:
                return (
                    SignalType.HOLD,
                    "Bearish Stoch RSI trigger rejected: Parabolic SAR is bullish",
                )
            if macd_line >= macd_signal or macd_histogram >= _DECIMAL_ZERO:
                return (
                    SignalType.HOLD,
                    "Bearish Stoch RSI trigger rejected: MACD momentum is not bearish",
                )
            if close_price <= lower_band:
                return (
                    SignalType.HOLD,
                    "Bearish Stoch RSI trigger rejected: Price extended at Lower Band",
                )
            return (
                SignalType.SELL,
                "Quad-Confluence SELL: Stoch RSI overbought crossover confirmed "
                "by SAR, MACD, and BB",
            )

        return (
            SignalType.HOLD,
            "Quad-Confluence setup absent",
        )

    @staticmethod
    def _calculate_confidence(
        *,
        signal_type: SignalType,
        curr_k: Decimal,
        curr_d: Decimal,
        macd_histogram: Decimal,
        close_price: Decimal,
    ) -> Decimal:
        """Calculate normalized confidence score bounded in [0.65, 0.95]."""
        if signal_type is SignalType.HOLD:
            return _DECIMAL_ZERO

        # Stoch separation quality (up to 0.15)
        stoch_gap = min(abs(curr_k - curr_d) / Decimal("20"), _DECIMAL_ONE)
        stoch_bonus = stoch_gap * _STOCH_WEIGHT

        # MACD momentum expansion quality (up to 0.15)
        if close_price > _DECIMAL_ZERO:
            hist_rel = min(
                abs(macd_histogram) / close_price / Decimal("0.002"),
                _DECIMAL_ONE,
            )
        else:
            hist_rel = _DECIMAL_ZERO
        macd_bonus = hist_rel * _MACD_WEIGHT

        return min(_BASE_CONFIDENCE + stoch_bonus + macd_bonus, _MAX_CONFIDENCE)
