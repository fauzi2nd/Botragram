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
    mtf_confirmation_enabled: bool = False
    mtf_interval: Interval = Interval.H1
    mtf_ema_period: int = 50
    discovery_filter_extreme_volatility: bool = True
    discovery_max_candle_volatility_pct: Decimal = Decimal("0.15")
    discovery_filter_min_liquidity: bool = True
    discovery_min_quote_volume_usdt: Decimal = Decimal("1000")
    use_open_interest: bool = False
    min_oi_change_pct: Decimal = Decimal("0.0")
    require_oi_confluence: bool = False
    filter_funding_sentiment: bool = True
    max_long_funding_rate: Decimal = Decimal("0.0005")
    min_short_funding_rate: Decimal = Decimal("-0.0005")
    require_funding_sentiment: bool = True
    filter_account_ratio: bool = True
    max_long_account_ratio: Decimal = Decimal("0.75")
    min_short_account_ratio: Decimal = Decimal("0.25")
    require_account_ratio_confluence: bool = True

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
    scalping_require_trend_filter: bool = False
    scalping_trend_period: int = 200

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
    choch_use_open_interest: bool = True
    choch_min_oi_change_pct: Decimal = Decimal("0.0")
    choch_oi_confidence_bonus: Decimal = Decimal("0.05")
    choch_require_oi_confluence: bool = False

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
    # Liquidity Sweep + Exhaustion (LSE)
    # =========================================================================
    lse_swing_lookback: int = 10
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
    lse_use_open_interest: bool = True
    lse_min_oi_change_pct: Decimal = Decimal("0.0")
    lse_oi_confidence_bonus: Decimal = Decimal("0.05")
    lse_require_oi_confluence: bool = False

    # =========================================================================
    # Quad-Confluence (Stoch RSI + Bollinger Bands + Parabolic SAR + MACD)
    # =========================================================================
    quad_rsi_period: int = 14
    quad_stoch_period: int = 14
    quad_k_period: int = 3
    quad_d_period: int = 3
    quad_stoch_oversold: Decimal = Decimal("20.0")
    quad_stoch_overbought: Decimal = Decimal("80.0")
    quad_bb_period: int = 20
    quad_bb_std_dev: Decimal = Decimal("2.0")
    quad_sar_step: Decimal = Decimal("0.02")
    quad_sar_max_step: Decimal = Decimal("0.20")
    quad_macd_fast_period: int = 12
    quad_macd_slow_period: int = 26
    quad_macd_signal_period: int = 9

    # =========================================================================
    # Pinbar + Engulfing Candlestick EMA-RSI Pullback (PIER)
    # =========================================================================
    pier_trend_period: int = 200
    pier_pullback_period: int = 21
    pier_rsi_period: int = 14
    pier_rsi_long_min: Decimal = Decimal("35.0")
    pier_rsi_long_max: Decimal = Decimal("52.0")
    pier_rsi_short_min: Decimal = Decimal("48.0")
    pier_rsi_short_max: Decimal = Decimal("65.0")
    pier_volume_period: int = 20
    pier_volume_multiplier: Decimal = Decimal("1.10")
    pier_min_wick_ratio: Decimal = Decimal("0.60")
    pier_max_opposite_wick_ratio: Decimal = Decimal("0.20")
    pier_min_engulfing_body_ratio: Decimal = Decimal("1.05")
    pier_atr_period: int = 14
    pier_atr_sl_multiplier: Decimal = Decimal("0.5")
    pier_risk_reward_ratio: Decimal = Decimal("2.0")
    pier_min_confidence: Decimal = Decimal("0.65")
    pier_use_open_interest: bool = True
    pier_min_oi_change_pct: Decimal = Decimal("0.0")
    pier_oi_confidence_bonus: Decimal = Decimal("0.05")
    pier_require_oi_confluence: bool = False
    pier_require_key_level_location: bool = True
    pier_swing_lookback: int = 15
    pier_require_trend_filter: bool = True
    pier_min_natr_threshold: Decimal = Decimal("0.0020")
    pier_min_sl_distance_pct: Decimal = Decimal("0.0080")
    pier_filter_account_ratio: bool = True
    pier_max_long_account_ratio: Decimal = Decimal("0.75")
    pier_min_short_account_ratio: Decimal = Decimal("0.25")
    pier_require_account_ratio_confluence: bool = False

    # =========================================================================
    # Market Orderflow Regime & Price-Hunt (MORPH)
    # =========================================================================
    morph_swing_lookback: int = 15
    morph_fvg_lookback: int = 20
    morph_min_wick_ratio: Decimal = Decimal("0.50")
    morph_volume_period: int = 20
    morph_volume_multiplier: Decimal = Decimal("1.15")
    morph_atr_period: int = 14
    morph_atr_multiplier_sl: Decimal = Decimal("0.8")
    morph_risk_reward_ratio: Decimal = Decimal("2.0")
    morph_min_confidence: Decimal = Decimal("0.65")
    morph_trend_period: int = 200
    morph_intermediate_trend_period: int = 50
    morph_require_trend_filter: bool = True
    morph_min_natr_threshold: Decimal = Decimal("0.0020")
    morph_use_fvg: bool = True
    morph_use_open_interest: bool = True
    morph_min_oi_change_pct: Decimal = Decimal("0.0")
    morph_oi_confidence_bonus: Decimal = Decimal("0.05")
    morph_require_oi_confluence: bool = False
    morph_filter_funding_sentiment: bool = True
    morph_max_long_funding_rate: Decimal = Decimal("0.0005")
    morph_min_short_funding_rate: Decimal = Decimal("-0.0005")
    morph_require_funding_sentiment: bool = True

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
        if not (
            Decimal("0") < self.discovery_max_candle_volatility_pct <= Decimal("1")
        ):
            raise ValueError(
                "Discovery max candle volatility pct must be between 0 and 1"
            )
        if self.discovery_min_quote_volume_usdt < Decimal("0"):
            raise ValueError("Discovery min quote volume USDT must not be negative")
        if self.scalping_fast_period <= 0 or self.scalping_slow_period <= 0:
            raise ValueError("Scalping EMA periods must be positive")
        if self.scalping_fast_period >= self.scalping_slow_period:
            raise ValueError("Scalping fast period must be less than slow period")
        if not (Decimal("0") <= self.scalping_minimum_body_ratio <= Decimal("1")):
            raise ValueError("Scalping minimum body ratio must be between 0 and 1")
        if self.scalping_trend_period <= 0:
            raise ValueError("Scalping trend period must be positive")
        if self.scalping_trend_period <= self.scalping_slow_period:
            raise ValueError("Scalping trend period must be greater than slow period")
        if (
            self.quad_rsi_period <= 0
            or self.quad_stoch_period <= 0
            or self.quad_k_period <= 0
            or self.quad_d_period <= 0
        ):
            raise ValueError("Quad-Confluence oscillator periods must be positive")
        if not (
            Decimal("0")
            <= self.quad_stoch_oversold
            < self.quad_stoch_overbought
            <= Decimal("100")
        ):
            raise ValueError(
                "Quad-Confluence Stoch RSI thresholds must be bounded within [0, 100]"
            )
        if self.quad_bb_period <= 0 or self.quad_bb_std_dev <= Decimal("0"):
            raise ValueError(
                "Quad-Confluence Bollinger Bands parameters must be positive"
            )
        if self.quad_sar_step <= Decimal("0") or self.quad_sar_max_step <= Decimal("0"):
            raise ValueError(
                "Quad-Confluence Parabolic SAR step parameters must be positive"
            )
        if self.quad_sar_step > self.quad_sar_max_step:
            raise ValueError(
                "Quad-Confluence Parabolic SAR step must not exceed maximum step"
            )
        if (
            self.quad_macd_fast_period <= 0
            or self.quad_macd_slow_period <= 0
            or self.quad_macd_signal_period <= 0
        ):
            raise ValueError("Quad-Confluence MACD periods must be positive")
        if self.quad_macd_fast_period >= self.quad_macd_slow_period:
            raise ValueError(
                "Quad-Confluence MACD fast period must be less than slow period"
            )
        if self.pier_trend_period <= 0 or self.pier_pullback_period <= 0:
            raise ValueError("PIER EMA periods must be positive")
        if self.pier_pullback_period >= self.pier_trend_period:
            raise ValueError("PIER pullback period must be less than trend period")
        if self.pier_rsi_period <= 0 or self.pier_atr_period <= 0:
            raise ValueError("PIER RSI and ATR periods must be positive")
        if not (
            Decimal("0")
            <= self.pier_rsi_long_min
            < self.pier_rsi_long_max
            <= Decimal("100")
        ):
            raise ValueError("PIER RSI long thresholds must be bounded within [0, 100]")
        if not (
            Decimal("0")
            <= self.pier_rsi_short_min
            < self.pier_rsi_short_max
            <= Decimal("100")
        ):
            raise ValueError(
                "PIER RSI short thresholds must be bounded within [0, 100]"
            )
        if self.pier_volume_period <= 0 or self.pier_volume_multiplier <= Decimal("0"):
            raise ValueError("PIER volume parameters must be positive")
        if not (Decimal("0") < self.pier_min_wick_ratio <= Decimal("1")):
            raise ValueError("PIER min wick ratio must be between 0 and 1")
        if not (Decimal("0") <= self.pier_max_opposite_wick_ratio <= Decimal("1")):
            raise ValueError("PIER max opposite wick ratio must be between 0 and 1")
        if self.pier_min_engulfing_body_ratio <= Decimal("0"):
            raise ValueError("PIER min engulfing body ratio must be positive")
        if self.pier_atr_sl_multiplier <= Decimal(
            "0"
        ) or self.pier_risk_reward_ratio <= Decimal("0"):
            raise ValueError("PIER ATR multiplier and RR ratio must be positive")
        if not (Decimal("0.0") <= self.pier_min_confidence <= Decimal("1.0")):
            raise ValueError("PIER minimum confidence must be between 0.0 and 1.0")
        if self.min_oi_change_pct < Decimal("0.0"):
            raise ValueError("Minimum OI change percentage must be non-negative")
        if self.pier_min_oi_change_pct < Decimal("0.0"):
            raise ValueError("PIER minimum OI change percentage must be non-negative")
        if self.pier_oi_confidence_bonus < Decimal("0.0"):
            raise ValueError("PIER OI confidence bonus must be non-negative")
        if self.pier_min_natr_threshold < Decimal("0"):
            raise ValueError("pier_min_natr_threshold must not be negative")
        if self.pier_min_sl_distance_pct < Decimal("0"):
            raise ValueError("pier_min_sl_distance_pct must not be negative")
        if self.morph_swing_lookback <= 2 or self.morph_fvg_lookback <= 2:
            raise ValueError("MORPH swing and FVG lookback must be greater than 2")
        if self.morph_volume_period <= 2 or self.morph_volume_multiplier <= Decimal(
            "0"
        ):
            raise ValueError("MORPH volume parameters must be positive")
        if self.morph_atr_period <= 2 or self.morph_atr_multiplier_sl <= Decimal("0"):
            raise ValueError("MORPH ATR parameters must be positive")
        if self.morph_trend_period <= 0 or self.morph_intermediate_trend_period <= 0:
            raise ValueError("MORPH trend periods must be positive")
        if self.morph_intermediate_trend_period >= self.morph_trend_period:
            raise ValueError(
                "morph_intermediate_trend_period must be less than morph_trend_period"
            )
        if self.morph_min_natr_threshold < Decimal("0"):
            raise ValueError("morph_min_natr_threshold must not be negative")
        if self.min_short_funding_rate > self.max_long_funding_rate:
            raise ValueError(
                "min_short_funding_rate cannot exceed max_long_funding_rate"
            )
        if self.morph_min_short_funding_rate > self.morph_max_long_funding_rate:
            raise ValueError(
                "morph_min_short_funding_rate cannot exceed morph_max_long_funding_rate"
            )
