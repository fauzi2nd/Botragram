"""
Botragram

Description:
    Trading strategy factory.

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
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.strategy_settings import StrategySettings
from botragram.enums import StrategyType
from botragram.strategies.base import BaseStrategy
from botragram.strategies.breakout import BollingerBreakoutStrategy
from botragram.strategies.price_action import (
    BotragramOriginStrategy,
    ChochFvgStrategy,
    ChochRsiBbHybridStrategy,
    HighConfluenceExhaustionStrategy,
    LiquiditySweepExhaustionStrategy,
    MorphStrategy,
    PinbarEngulfingEmaRsiStrategy,
)
from botragram.strategies.scalping import (
    EMAScalpingStrategy,
    NY4HRangeScalpingStrategy,
    RSIBBScalpingStrategy,
    VWAPBreakoutStrategy,
)
from botragram.strategies.swing import (
    MACDSwingStrategy,
)
from botragram.strategies.trend import (
    ADXTrendStrategy,
    EMACrossStrategy,
    EMARsiStrategy,
    IchimokuCloudStrategy,
    QuadConfluenceStrategy,
    SupertrendStrategy,
)

__all__ = [
    "StrategyFactory",
    "StrategyResolver",
]


# =============================================================================
# Strategy Resolution
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class StrategyResolver:
    """Resolve immutable strategy instances from explicit strategy types."""

    strategies: Mapping[StrategyType, BaseStrategy]

    def __post_init__(self) -> None:
        """Copy and validate the resolver registry before exposing it."""
        registry = dict(self.strategies)

        for strategy_type, strategy in registry.items():
            if strategy.strategy_type is not strategy_type:
                raise ValueError(
                    "Strategy resolver key does not match strategy instance: "
                    f"{strategy_type.value!r}"
                )

        object.__setattr__(self, "strategies", MappingProxyType(registry))

    def resolve(self, *, strategy_type: StrategyType) -> BaseStrategy:
        """Return the strategy registered for one explicit strategy type.

        Args:
            strategy_type: The context-authoritative strategy type.

        Returns:
            The matching immutable strategy instance.

        Raises:
            ValueError: If the type has no registered strategy.
        """
        strategy = self.strategies.get(strategy_type)

        if strategy is None:
            raise ValueError(f"Unsupported strategy type: {strategy_type.value!r}")

        return strategy


# =============================================================================
# Strategy Factory
# =============================================================================
class StrategyFactory:
    """Create trading strategies from strategy settings."""

    __slots__ = ()

    @staticmethod
    def create(
        *,
        settings: StrategySettings,
    ) -> BaseStrategy:
        """Create a trading strategy.

        Args:
            settings: Strategy configuration settings.

        Returns:
            Configured trading strategy.

        Raises:
            ValueError: If the configured strategy is unsupported.
        """
        match settings.strategy_type:
            case StrategyType.ADX_TREND:
                return ADXTrendStrategy(
                    adx_period=settings.adx_period,
                    fast_period=settings.adx_fast_period,
                    slow_period=settings.adx_slow_period,
                    adx_threshold=settings.adx_threshold,
                )

            case StrategyType.BOLLINGER_BREAKOUT:
                return BollingerBreakoutStrategy(
                    period=settings.bb_period,
                    standard_deviation=settings.bb_standard_deviation,
                )

            case StrategyType.BOTRAGRAM_ORIGIN:
                return BotragramOriginStrategy(
                    risk_reward_ratio=settings.origin_risk_reward_ratio,
                    min_sl_pct=settings.origin_min_sl_pct,
                    max_sl_pct=settings.origin_max_sl_pct,
                    fallback_sl_pct=settings.origin_fallback_sl_pct,
                    min_confidence=settings.origin_min_confidence,
                    use_trend_filter=settings.origin_use_trend_filter,
                    trend_ema_period=settings.origin_trend_ema_period,
                    use_volume_filter=settings.origin_use_volume_filter,
                    volume_period=settings.origin_volume_period,
                    volume_multiplier=settings.origin_volume_multiplier,
                    use_rsi_filter=settings.origin_use_rsi_filter,
                    rsi_period=settings.origin_rsi_period,
                    rsi_long_max=settings.origin_rsi_long_max,
                    rsi_short_min=settings.origin_rsi_short_min,
                    require_rsi_direction=settings.origin_require_rsi_direction,
                    use_bb_filter=settings.origin_use_bb_filter,
                    bb_period=settings.origin_bb_period,
                    bb_std_dev=settings.origin_bb_std_dev,
                    use_macd_filter=settings.origin_use_macd_filter,
                    macd_fast_period=settings.origin_macd_fast_period,
                    macd_slow_period=settings.origin_macd_slow_period,
                    macd_signal_period=settings.origin_macd_signal_period,
                    use_psar_filter=settings.origin_use_psar_filter,
                    psar_max_proximity_pct=settings.origin_psar_max_proximity_pct,
                )

            case StrategyType.CHOCH_FVG:
                return ChochFvgStrategy(
                    swing_window=settings.choch_swing_window,
                    fvg_lookback=settings.choch_fvg_lookback,
                    volume_period=settings.choch_volume_period,
                    volume_multiplier=settings.choch_volume_multiplier,
                    min_body_ratio=settings.choch_min_body_ratio,
                    min_gap_ratio=settings.choch_min_gap_ratio,
                    trend_period=settings.choch_trend_period,
                    intermediate_trend_period=settings.choch_intermediate_trend_period,
                    min_confidence=settings.choch_min_confidence,
                    use_open_interest=settings.choch_use_open_interest
                    or settings.use_open_interest,
                    min_oi_change_pct=(
                        settings.choch_min_oi_change_pct
                        if settings.choch_min_oi_change_pct > Decimal("0")
                        else settings.min_oi_change_pct
                    ),
                    oi_confidence_bonus=settings.choch_oi_confidence_bonus,
                    require_oi_confluence=settings.choch_require_oi_confluence
                    or settings.require_oi_confluence,
                )

            case StrategyType.CHOCH_RSI_BB_HYBRID:
                return ChochRsiBbHybridStrategy(
                    swing_window=settings.crbb_swing_window,
                    fvg_lookback=settings.crbb_fvg_lookback,
                    volume_period=settings.crbb_volume_period,
                    volume_multiplier=settings.crbb_volume_multiplier,
                    min_gap_ratio=settings.crbb_min_gap_ratio,
                    trend_period=settings.crbb_trend_period,
                    intermediate_trend_period=settings.crbb_intermediate_trend_period,
                    bb_period=settings.crbb_bb_period,
                    bb_standard_deviation=settings.crbb_bb_std_dev,
                    rsi_period=settings.crbb_rsi_period,
                    rsi_oversold=settings.crbb_rsi_oversold,
                    rsi_overbought=settings.crbb_rsi_overbought,
                    adx_period=settings.crbb_adx_period,
                    adx_ranging_threshold=settings.crbb_adx_ranging_threshold,
                    atr_period=settings.crbb_atr_period,
                    max_natr_threshold=settings.crbb_max_natr_threshold,
                    min_wick_ratio=settings.crbb_min_wick_ratio,
                    strong_wick_ratio=settings.crbb_strong_wick_ratio,
                    min_confidence=settings.crbb_min_confidence,
                    cooldown_bars=settings.crbb_cooldown_bars,
                    max_hold_bars=settings.crbb_max_hold_bars,
                    short_bias_multiplier=settings.crbb_short_bias_multiplier,
                )

            case StrategyType.EMA_CROSS:
                return EMACrossStrategy(
                    fast_period=settings.fast_period,
                    slow_period=settings.slow_period,
                )

            case StrategyType.EMA_RSI:
                return EMARsiStrategy(
                    fast_period=settings.fast_period,
                    slow_period=settings.slow_period,
                    rsi_period=settings.rsi_period,
                    rsi_overbought=settings.rsi_overbought,
                    rsi_oversold=settings.rsi_oversold,
                )

            case StrategyType.EMA_SCALPING:
                return EMAScalpingStrategy(
                    fast_period=settings.scalping_fast_period,
                    slow_period=settings.scalping_slow_period,
                    minimum_body_ratio=settings.scalping_minimum_body_ratio,
                    require_trend_filter=settings.scalping_require_trend_filter,
                    trend_period=settings.scalping_trend_period,
                )

            case StrategyType.HIGH_CONFLUENCE_EXHAUSTION:
                return HighConfluenceExhaustionStrategy(
                    bb_period=settings.hce_bb_period,
                    bb_std_dev=settings.hce_bb_std_dev,
                    rsi_period=settings.hce_rsi_period,
                    rsi_oversold=settings.hce_rsi_oversold,
                    rsi_overbought=settings.hce_rsi_overbought,
                    volume_period=settings.hce_volume_period,
                    volume_multiplier=settings.hce_volume_multiplier,
                    adx_period=settings.hce_adx_period,
                    adx_max_threshold=settings.hce_adx_max_threshold,
                    trend_period=settings.hce_trend_period,
                    intermediate_trend_period=settings.hce_intermediate_trend_period,
                    swing_lookback=settings.hce_swing_lookback,
                )

            case StrategyType.ICHIMOKU_CLOUD:
                return IchimokuCloudStrategy(
                    conversion_period=settings.ichimoku_conversion_period,
                    base_period=settings.ichimoku_base_period,
                    leading_span_period=settings.ichimoku_leading_span_period,
                )

            case StrategyType.LIQUIDITY_SWEEP_EXHAUSTION:
                return LiquiditySweepExhaustionStrategy(
                    swing_lookback=settings.lse_swing_lookback,
                    min_wick_ratio=settings.lse_min_wick_ratio,
                    volume_period=settings.lse_volume_period,
                    volume_multiplier=settings.lse_volume_multiplier,
                    rsi_period=settings.lse_rsi_period,
                    rsi_oversold=settings.lse_rsi_oversold,
                    rsi_overbought=settings.lse_rsi_overbought,
                    atr_period=settings.lse_atr_period,
                    atr_multiplier_sl=settings.lse_atr_multiplier_sl,
                    atr_multiplier_tp1=settings.lse_atr_multiplier_tp1,
                    atr_multiplier_tp2=settings.lse_atr_multiplier_tp2,
                    min_natr_threshold=settings.lse_min_natr_threshold,
                    max_natr_threshold=settings.lse_max_natr_threshold,
                    filter_funding=settings.lse_filter_funding,
                    funding_buffer_minutes=settings.lse_funding_buffer_minutes,
                    min_confidence=settings.lse_min_confidence,
                    cooldown_bars=settings.lse_cooldown_bars,
                    max_hold_bars=settings.lse_max_hold_bars,
                    short_bias_multiplier=settings.lse_short_bias_multiplier,
                    use_open_interest=settings.lse_use_open_interest
                    or settings.use_open_interest,
                    min_oi_change_pct=(
                        settings.lse_min_oi_change_pct
                        if settings.lse_min_oi_change_pct > Decimal("0")
                        else settings.min_oi_change_pct
                    ),
                    oi_confidence_bonus=settings.lse_oi_confidence_bonus,
                    require_oi_confluence=settings.lse_require_oi_confluence
                    or settings.require_oi_confluence,
                )

            case StrategyType.MACD_SWING:
                return MACDSwingStrategy(
                    fast_period=settings.macd_fast_period,
                    slow_period=settings.macd_slow_period,
                    signal_period=settings.macd_signal_period,
                )

            case StrategyType.MORPH:
                return MorphStrategy(
                    swing_lookback=settings.morph_swing_lookback,
                    fvg_lookback=settings.morph_fvg_lookback,
                    use_fvg=settings.morph_use_fvg,
                    min_wick_ratio=settings.morph_min_wick_ratio,
                    volume_period=settings.morph_volume_period,
                    volume_multiplier=settings.morph_volume_multiplier,
                    atr_period=settings.morph_atr_period,
                    atr_multiplier_sl=settings.morph_atr_multiplier_sl,
                    risk_reward_ratio=settings.morph_risk_reward_ratio,
                    min_confidence=settings.morph_min_confidence,
                    trend_period=settings.morph_trend_period,
                    intermediate_trend_period=settings.morph_intermediate_trend_period,
                    require_trend_filter=settings.morph_require_trend_filter,
                    min_natr_threshold=settings.morph_min_natr_threshold,
                    use_open_interest=settings.morph_use_open_interest
                    or settings.use_open_interest,
                    min_oi_change_pct=(
                        settings.morph_min_oi_change_pct
                        if settings.morph_min_oi_change_pct > Decimal("0")
                        else settings.min_oi_change_pct
                    ),
                    oi_confidence_bonus=settings.morph_oi_confidence_bonus,
                    require_oi_confluence=settings.morph_require_oi_confluence
                    or settings.require_oi_confluence,
                    filter_funding_sentiment=(
                        settings.morph_filter_funding_sentiment
                        and settings.filter_funding_sentiment
                    ),
                    max_long_funding_rate=settings.morph_max_long_funding_rate,
                    min_short_funding_rate=settings.morph_min_short_funding_rate,
                    require_funding_sentiment=(
                        settings.morph_require_funding_sentiment
                        and settings.require_funding_sentiment
                    ),
                )

            case StrategyType.NY_4H_RANGE_SCALPING:
                return NY4HRangeScalpingStrategy(
                    risk_reward_ratio=settings.ny_range_risk_reward_ratio,
                    max_sl_pct=settings.ny_range_max_sl_pct,
                    min_sl_pct=settings.ny_range_min_sl_pct,
                    fallback_sl_pct=settings.ny_range_fallback_sl_pct,
                    max_breakout_bars=settings.ny_range_max_breakout_bars,
                    min_confidence=settings.ny_range_min_confidence,
                    base_confidence=settings.ny_range_base_confidence,
                    use_volume_filter=settings.ny_range_use_volume_filter,
                    volume_period=settings.ny_range_volume_period,
                    volume_multiplier=settings.ny_range_volume_multiplier,
                    volume_confidence_bonus=(settings.ny_range_volume_confidence_bonus),
                    require_volume_confirmation=(
                        settings.ny_range_require_volume_confirmation
                    ),
                    require_trend_filter=settings.ny_range_require_trend_filter,
                    trend_ema_period=settings.ny_range_trend_ema_period,
                    use_rsi_filter=settings.ny_range_use_rsi_filter,
                    rsi_period=settings.ny_range_rsi_period,
                    rsi_long_max=settings.ny_range_rsi_long_max,
                    rsi_short_min=settings.ny_range_rsi_short_min,
                    use_open_interest=settings.use_open_interest,
                    min_oi_change_pct=settings.min_oi_change_pct,
                    require_oi_confluence=settings.require_oi_confluence,
                )

            case StrategyType.PINBAR_ENGULFING_EMA_RSI:
                return PinbarEngulfingEmaRsiStrategy(
                    trend_period=settings.pier_trend_period,
                    pullback_period=settings.pier_pullback_period,
                    rsi_period=settings.pier_rsi_period,
                    rsi_long_min=settings.pier_rsi_long_min,
                    rsi_long_max=settings.pier_rsi_long_max,
                    rsi_short_min=settings.pier_rsi_short_min,
                    rsi_short_max=settings.pier_rsi_short_max,
                    volume_period=settings.pier_volume_period,
                    volume_multiplier=settings.pier_volume_multiplier,
                    min_wick_ratio=settings.pier_min_wick_ratio,
                    max_opposite_wick_ratio=settings.pier_max_opposite_wick_ratio,
                    min_engulfing_body_ratio=settings.pier_min_engulfing_body_ratio,
                    min_confidence=settings.pier_min_confidence,
                    use_open_interest=settings.pier_use_open_interest
                    or settings.use_open_interest,
                    min_oi_change_pct=(
                        settings.pier_min_oi_change_pct
                        if settings.pier_min_oi_change_pct > Decimal("0")
                        else settings.min_oi_change_pct
                    ),
                    oi_confidence_bonus=settings.pier_oi_confidence_bonus,
                    require_oi_confluence=settings.pier_require_oi_confluence
                    or settings.require_oi_confluence,
                    require_key_level_location=settings.pier_require_key_level_location,
                    swing_lookback=settings.pier_swing_lookback,
                    location_tolerance_pct=settings.pier_location_tolerance_pct,
                    location_atr_multiplier=settings.pier_location_atr_multiplier,
                    pullback_proximity_pct=settings.pier_pullback_proximity_pct,
                    pullback_atr_multiplier=settings.pier_pullback_atr_multiplier,
                    pinbar_min_range_atr=settings.pier_pinbar_min_range_atr,
                    engulfing_min_body_atr=settings.pier_engulfing_min_body_atr,
                    require_confirmation=settings.pier_require_confirmation,
                    atr_period=settings.pier_atr_period,
                    atr_multiplier_sl=settings.pier_atr_sl_multiplier,
                    risk_reward_ratio=settings.pier_risk_reward_ratio,
                    require_trend_filter=settings.pier_require_trend_filter,
                    min_natr_threshold=settings.pier_min_natr_threshold,
                    min_sl_distance_pct=settings.pier_min_sl_distance_pct,
                    filter_account_ratio=settings.pier_filter_account_ratio
                    or settings.filter_account_ratio,
                    max_long_account_ratio=settings.pier_max_long_account_ratio,
                    min_short_account_ratio=settings.pier_min_short_account_ratio,
                    require_account_ratio_confluence=(
                        settings.pier_require_account_ratio_confluence
                        or settings.require_account_ratio_confluence
                    ),
                    confirm_htf_account_ratio=(
                        settings.pier_confirm_htf_account_ratio
                        or settings.confirm_htf_account_ratio
                    ),
                    include_star_patterns=settings.pier_include_star_patterns,
                    use_parabolic_sar=settings.pier_use_parabolic_sar,
                    use_macd=settings.pier_use_macd,
                    macd_fast_period=settings.pier_macd_fast_period,
                    macd_slow_period=settings.pier_macd_slow_period,
                    macd_signal_period=settings.pier_macd_signal_period,
                    use_stoch_rsi=settings.pier_use_stoch_rsi,
                    stoch_rsi_period=settings.pier_stoch_rsi_period,
                    stoch_rsi_k_period=settings.pier_stoch_rsi_k_period,
                    stoch_rsi_d_period=settings.pier_stoch_rsi_d_period,
                    stoch_rsi_overbought=settings.pier_stoch_rsi_overbought,
                    stoch_rsi_oversold=settings.pier_stoch_rsi_oversold,
                )

            case StrategyType.QUAD_CONFLUENCE:
                return QuadConfluenceStrategy(
                    rsi_period=settings.quad_rsi_period,
                    stoch_period=settings.quad_stoch_period,
                    k_period=settings.quad_k_period,
                    d_period=settings.quad_d_period,
                    stoch_oversold=settings.quad_stoch_oversold,
                    stoch_overbought=settings.quad_stoch_overbought,
                    bb_period=settings.quad_bb_period,
                    bb_std_dev=settings.quad_bb_std_dev,
                    sar_step=settings.quad_sar_step,
                    sar_max_step=settings.quad_sar_max_step,
                    macd_fast_period=settings.quad_macd_fast_period,
                    macd_slow_period=settings.quad_macd_slow_period,
                    macd_signal_period=settings.quad_macd_signal_period,
                )

            case StrategyType.RSI_BB_SCALPING:
                return RSIBBScalpingStrategy(
                    bb_period=settings.bb_period,
                    bb_standard_deviation=settings.bb_standard_deviation,
                    rsi_period=settings.rsi_period,
                    rsi_overbought=settings.rsi_overbought,
                    rsi_oversold=settings.rsi_oversold,
                )

            case StrategyType.SUPERTREND:
                return SupertrendStrategy(
                    period=settings.supertrend_period,
                    multiplier=settings.supertrend_multiplier,
                )

            case StrategyType.VWAP_BREAKOUT:
                return VWAPBreakoutStrategy(
                    atr_period=settings.atr_period,
                    volume_period=settings.vwap_volume_period,
                    volume_multiplier=settings.vwap_volume_multiplier,
                )

            case _:
                raise ValueError(
                    f"Unsupported strategy type: {settings.strategy_type.value!r}"
                )

    @staticmethod
    def create_resolver(*, settings: StrategySettings) -> StrategyResolver:
        """Construct one reusable immutable strategy per supported type.

        Args:
            settings: Shared parameter settings used to construct each strategy.

        Returns:
            A deterministic resolver with no mutable current-strategy state.
        """
        if settings.strategy_type is StrategyType.CUSTOM:
            raise ValueError(
                f"Unsupported strategy type: {settings.strategy_type.value!r}"
            )

        return StrategyResolver(
            strategies={
                strategy_type: StrategyFactory.create(
                    settings=replace(settings, strategy_type=strategy_type),
                )
                for strategy_type in StrategyType
                if strategy_type is not StrategyType.CUSTOM
            },
        )
