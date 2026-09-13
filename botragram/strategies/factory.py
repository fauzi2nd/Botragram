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
    ChochFvgStrategy,
    ChochRsiBbHybridStrategy,
    HighConfluenceExhaustionStrategy,
    LiquiditySweepExhaustionStrategy,
    MorphStrategy,
    PinbarEngulfingEmaRsiStrategy,
)
from botragram.strategies.scalping import (
    EMAScalpingStrategy,
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
