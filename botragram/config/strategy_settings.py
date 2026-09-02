"""
Botragram

Description:
    Strategy parameter configuration model.

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
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.strategy import get_strategy_default_interval
from botragram.enums import Interval, StrategyType

__all__ = [
    "StrategySettings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class StrategySettings:
    """Settings controlling indicator periods and strategy behavior."""

    strategy_type: StrategyType = StrategyType.EMA_CROSS
    invert_signals: bool = False
    min_signal_confidence: Decimal = Decimal("0.0")

    @property
    def default_interval(self) -> Interval:
        """Return the default optimal candlestick interval for this strategy."""
        return get_strategy_default_interval(self.strategy_type)

    # ============================================================================
    # EMA Cross
    # ============================================================================
    fast_period: int = 9
    slow_period: int = 21

    # ============================================================================
    # RSI
    # ============================================================================
    rsi_period: int = 14
    rsi_overbought: Decimal = Decimal("70.0")
    rsi_oversold: Decimal = Decimal("30.0")

    # ============================================================================
    # MACD
    # ============================================================================
    macd_fast_period: int = 12
    macd_slow_period: int = 26
    macd_signal_period: int = 9

    # ============================================================================
    # Bollinger Bands
    # ============================================================================
    bb_period: int = 20
    bb_standard_deviation: Decimal = Decimal("2.0")

    # =========================================================================
    # Supertrend
    # =========================================================================
    supertrend_period: int = 10
    supertrend_multiplier: Decimal = Decimal("3")

    # =========================================================================
    # EMA Scalping
    # =========================================================================
    scalping_fast_period: int = 5
    scalping_slow_period: int = 13
    scalping_minimum_body_ratio: Decimal = Decimal("0.25")

    # =========================================================================
    # Ichimoku Cloud
    # =========================================================================
    ichimoku_conversion_period: int = 9
    ichimoku_base_period: int = 26
    ichimoku_leading_span_period: int = 52

    # =========================================================================
    # ADX Trend
    # =========================================================================
    adx_period: int = 14
    adx_fast_period: int = 9
    adx_slow_period: int = 21
    adx_threshold: Decimal = Decimal("25.0")

    # =========================================================================
    # VWAP & Volatility Breakout
    # =========================================================================
    atr_period: int = 14
    vwap_volume_period: int = 20
    vwap_volume_multiplier: Decimal = Decimal("1.2")

    # =========================================================================
    # CHoCH + FVG (Smart Money Concepts)
    # =========================================================================
    choch_swing_window: int = 5
    choch_fvg_lookback: int = 20
    choch_min_body_ratio: Decimal = Decimal("0.50")
    choch_volume_multiplier: Decimal = Decimal("1.2")

    # =========================================================================
    # High Confluence Exhaustion
    # =========================================================================
    hce_bb_period: int = 20
    hce_bb_std_dev: Decimal = Decimal("2.0")
    hce_rsi_period: int = 14
    hce_rsi_oversold: Decimal = Decimal("28.0")
    hce_rsi_overbought: Decimal = Decimal("72.0")
    hce_volume_period: int = 20
    hce_volume_multiplier: Decimal = Decimal("1.3")
    hce_adx_period: int = 14
    hce_adx_max_threshold: Decimal = Decimal("42.0")
    hce_trend_period: int = 50
    hce_swing_lookback: int = 10

    def __post_init__(self) -> None:
        """Validate bounded strategy settings."""
        if not self.min_signal_confidence.is_finite():
            raise ValueError("Minimum signal confidence must be finite")
        if not Decimal("0.0") <= self.min_signal_confidence <= Decimal("1.0"):
            raise ValueError("Minimum signal confidence must be between 0.0 and 1.0")
        if self.hce_bb_period <= 0:
            raise ValueError("HCE Bollinger Bands period must be positive")
        if self.hce_bb_std_dev <= Decimal("0"):
            raise ValueError("HCE Bollinger Bands std dev must be positive")
        if self.hce_rsi_period <= 0:
            raise ValueError("HCE RSI period must be positive")
        if (
            not Decimal("0")
            <= self.hce_rsi_oversold
            < self.hce_rsi_overbought
            <= Decimal("100")
        ):
            raise ValueError("HCE RSI thresholds must be bounded within [0, 100]")
        if self.hce_volume_period <= 0 or self.hce_volume_multiplier <= Decimal("0"):
            raise ValueError("HCE Volume parameters must be positive")
        if self.hce_adx_period <= 0 or self.hce_adx_max_threshold <= Decimal("0"):
            raise ValueError("HCE ADX parameters must be positive")
        if self.hce_trend_period <= 0 or self.hce_swing_lookback <= 0:
            raise ValueError("HCE lookback periods must be positive")
