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
    choch_swing_window: int = 8
    choch_fvg_lookback: int = 20
    choch_volume_period: int = 20
    choch_min_body_ratio: Decimal = Decimal("0.60")
    choch_volume_multiplier: Decimal = Decimal("1.35")
    choch_min_gap_ratio: Decimal = Decimal("0.0015")
    choch_trend_period: int = 200
    choch_intermediate_trend_period: int = 50
    choch_min_confidence: Decimal = Decimal("0.75")

    # =========================================================================
    # High Confluence Exhaustion
    # =========================================================================
    hce_bb_period: int = 20
    hce_bb_std_dev: Decimal = Decimal("2.0")
    hce_rsi_period: int = 14
    hce_rsi_oversold: Decimal = Decimal("32.0")
    hce_rsi_overbought: Decimal = Decimal("68.0")
    hce_volume_period: int = 20
    hce_volume_multiplier: Decimal = Decimal("1.2")
    hce_adx_period: int = 14
    hce_adx_max_threshold: Decimal = Decimal("42.0")
    hce_trend_period: int = 200
    hce_intermediate_trend_period: int = 50
    hce_swing_lookback: int = 10

    # =========================================================================
    # CHoCH + RSI/BB Hybrid (Smart Money Structure + Mean Reversion)
    # =========================================================================
    crbb_swing_window: int = 5
    crbb_fvg_lookback: int = 20
    crbb_volume_period: int = 20
    crbb_volume_multiplier: Decimal = Decimal("1.05")
    crbb_min_gap_ratio: Decimal = Decimal("0.0008")
    crbb_trend_period: int = 100
    crbb_intermediate_trend_period: int = 30
    crbb_bb_period: int = 20
    crbb_bb_std_dev: Decimal = Decimal("2.0")
    crbb_rsi_period: int = 14
    crbb_rsi_oversold: Decimal = Decimal("35.0")
    crbb_rsi_overbought: Decimal = Decimal("65.0")
    crbb_adx_period: int = 14
    crbb_adx_ranging_threshold: Decimal = Decimal("35.0")
    crbb_atr_period: int = 14
    crbb_max_natr_threshold: Decimal = Decimal("0.040")
    crbb_min_wick_ratio: Decimal = Decimal("0.15")
    crbb_strong_wick_ratio: Decimal = Decimal("0.30")
    crbb_min_confidence: Decimal = Decimal("0.60")
    crbb_cooldown_bars: int = 2
    crbb_max_hold_bars: int = 24
    crbb_short_bias_multiplier: Decimal = Decimal("1.06")

    # =========================================================================
    # Liquidity Sweep Exhaustion (LSE Price Action Scalping)
    # =========================================================================
    lse_swing_lookback: int = 15
    lse_min_wick_ratio: Decimal = Decimal("0.50")
    lse_volume_period: int = 20
    lse_volume_multiplier: Decimal = Decimal("1.30")
    lse_rsi_period: int = 14
    lse_rsi_oversold: Decimal = Decimal("38.0")
    lse_rsi_overbought: Decimal = Decimal("62.0")
    lse_atr_period: int = 14
    lse_atr_multiplier_sl: Decimal = Decimal("1.2")
    lse_atr_multiplier_tp1: Decimal = Decimal("1.2")
    lse_atr_multiplier_tp2: Decimal = Decimal("2.0")
    lse_min_natr_threshold: Decimal = Decimal("0.0020")
    lse_max_natr_threshold: Decimal = Decimal("0.0350")
    lse_filter_funding: bool = True
    lse_funding_buffer_minutes: int = 15
    lse_min_confidence: Decimal = Decimal("0.60")
    lse_cooldown_bars: int = 2
    lse_max_hold_bars: int = 24
    lse_short_bias_multiplier: Decimal = Decimal("1.06")

    def __post_init__(self) -> None:
        """Validate bounded strategy settings."""
        if not self.min_signal_confidence.is_finite():
            raise ValueError("Minimum signal confidence must be finite")
        if not Decimal("0.0") <= self.min_signal_confidence <= Decimal("1.0"):
            raise ValueError("Minimum signal confidence must be between 0.0 and 1.0")
        if self.choch_swing_window <= 0 or self.choch_fvg_lookback <= 0:
            raise ValueError("CHoCH window parameters must be positive")
        if self.choch_volume_period <= 0 or self.choch_volume_multiplier <= Decimal(
            "0"
        ):
            raise ValueError("CHoCH volume parameters must be positive")
        if self.choch_min_body_ratio <= Decimal("0"):
            raise ValueError("CHoCH minimum body ratio must be positive")
        if self.choch_min_gap_ratio < Decimal("0"):
            raise ValueError("CHoCH minimum gap ratio must not be negative")
        if self.choch_trend_period <= 0 or self.choch_intermediate_trend_period <= 0:
            raise ValueError("CHoCH trend periods must be positive")
        if self.choch_intermediate_trend_period >= self.choch_trend_period:
            raise ValueError(
                "CHoCH intermediate_trend_period must be less than trend_period"
            )
        if not (Decimal("0.0") <= self.choch_min_confidence <= Decimal("1.0")):
            raise ValueError("CHoCH minimum confidence must be between 0.0 and 1.0")
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
        if self.hce_intermediate_trend_period <= 0:
            raise ValueError("HCE intermediate trend period must be positive")
        if self.hce_intermediate_trend_period >= self.hce_trend_period:
            raise ValueError(
                "HCE intermediate_trend_period must be less than trend_period"
            )
        if self.crbb_swing_window <= 0 or self.crbb_fvg_lookback <= 0:
            raise ValueError("CRBB window parameters must be positive")
        if self.crbb_volume_period <= 0 or self.crbb_volume_multiplier <= Decimal("0"):
            raise ValueError("CRBB volume parameters must be positive")
        if self.crbb_min_gap_ratio < Decimal("0"):
            raise ValueError("CRBB minimum gap ratio must not be negative")
        if self.crbb_trend_period <= 0 or self.crbb_intermediate_trend_period <= 0:
            raise ValueError("CRBB trend periods must be positive")
        if self.crbb_intermediate_trend_period >= self.crbb_trend_period:
            raise ValueError(
                "CRBB intermediate_trend_period must be less than trend_period"
            )
        if self.crbb_bb_period <= 0 or self.crbb_bb_std_dev <= Decimal("0"):
            raise ValueError("CRBB Bollinger Bands parameters must be positive")
        if self.crbb_rsi_period <= 0:
            raise ValueError("CRBB RSI period must be positive")
        if (
            not Decimal("0")
            <= self.crbb_rsi_oversold
            < self.crbb_rsi_overbought
            <= Decimal("100")
        ):
            raise ValueError("CRBB RSI thresholds must be bounded within [0, 100]")
        if self.crbb_adx_period <= 0 or self.crbb_adx_ranging_threshold <= Decimal("0"):
            raise ValueError("CRBB ADX parameters must be positive")
        if self.crbb_atr_period <= 0 or self.crbb_max_natr_threshold <= Decimal("0"):
            raise ValueError("CRBB ATR parameters must be positive")
        if not (
            Decimal("0")
            <= self.crbb_min_wick_ratio
            <= self.crbb_strong_wick_ratio
            <= Decimal("1")
        ):
            raise ValueError("CRBB wick ratios must be bounded within [0, 1]")
        if not (Decimal("0.0") <= self.crbb_min_confidence <= Decimal("1.0")):
            raise ValueError("CRBB minimum confidence must be between 0.0 and 1.0")
        if self.crbb_cooldown_bars < 0:
            raise ValueError("CRBB cooldown bars must not be negative")
        if self.crbb_max_hold_bars <= 0:
            raise ValueError("CRBB max hold bars must be positive")
        if self.crbb_short_bias_multiplier < Decimal("1.0"):
            raise ValueError("CRBB short bias multiplier must be at least 1.0")
        if self.lse_swing_lookback <= 0:
            raise ValueError("LSE swing lookback must be positive")
        if not (Decimal("0") < self.lse_min_wick_ratio <= Decimal("1")):
            raise ValueError("LSE min wick ratio must be between 0 and 1")
        if self.lse_volume_period <= 0 or self.lse_volume_multiplier <= Decimal("0"):
            raise ValueError("LSE volume parameters must be positive")
        if self.lse_rsi_period <= 0:
            raise ValueError("LSE RSI period must be positive")
        if not (
            Decimal("0")
            <= self.lse_rsi_oversold
            < self.lse_rsi_overbought
            <= Decimal("100")
        ):
            raise ValueError("LSE RSI thresholds must be bounded within [0, 100]")
        if self.lse_atr_period <= 0:
            raise ValueError("LSE ATR period must be positive")
        if (
            self.lse_atr_multiplier_sl <= Decimal("0")
            or self.lse_atr_multiplier_tp1 <= Decimal("0")
            or self.lse_atr_multiplier_tp2 <= Decimal("0")
        ):
            raise ValueError("LSE ATR multipliers must be positive")
        if not (
            Decimal("0") <= self.lse_min_natr_threshold < self.lse_max_natr_threshold
        ):
            raise ValueError("LSE NATR thresholds must be positive and ordered")
        if self.lse_funding_buffer_minutes < 0:
            raise ValueError("LSE funding buffer minutes must not be negative")
        if not (Decimal("0.0") <= self.lse_min_confidence <= Decimal("1.0")):
            raise ValueError("LSE minimum confidence must be between 0.0 and 1.0")
        if self.lse_cooldown_bars < 0:
            raise ValueError("LSE cooldown bars must not be negative")
        if self.lse_max_hold_bars <= 0:
            raise ValueError("LSE max hold bars must be positive")
        if self.lse_short_bias_multiplier < Decimal("1.0"):
            raise ValueError("LSE short bias multiplier must be at least 1.0")
