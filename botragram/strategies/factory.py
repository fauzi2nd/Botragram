"""Construct and resolve the sole active PIER strategy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from botragram.config.strategy_settings import StrategySettings
from botragram.enums import StrategyType
from botragram.strategies.base import BaseStrategy
from botragram.strategies.price_action import PinbarEngulfingEmaRsiStrategy

__all__ = ["StrategyFactory", "StrategyResolver"]


# =============================================================================
# Strategy Resolution
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class StrategyResolver:
    """Resolve immutable strategies from explicit context identifiers."""

    strategies: Mapping[StrategyType, BaseStrategy]

    def __post_init__(self) -> None:
        """Copy and validate strategy registrations before exposing them."""
        registry = dict(self.strategies)
        for strategy_type, strategy in registry.items():
            if strategy.strategy_type is not strategy_type:
                raise ValueError(
                    "Strategy resolver key does not match strategy instance: "
                    f"{strategy_type.value!r}"
                )
        object.__setattr__(self, "strategies", MappingProxyType(registry))

    def resolve(self, *, strategy_type: StrategyType) -> BaseStrategy:
        """Return a registered strategy or reject an unavailable identifier."""
        strategy = self.strategies.get(strategy_type)
        if strategy is None:
            raise ValueError(f"Unsupported strategy type: {strategy_type.value!r}")
        return strategy


# =============================================================================
# Strategy Factory
# =============================================================================
class StrategyFactory:
    """Create the sole active trading strategy from PIER settings."""

    __slots__ = ()

    @staticmethod
    def create(*, settings: StrategySettings) -> BaseStrategy:
        """Create PIER or reject a legacy strategy configuration."""
        if settings.strategy_type is not StrategyType.PINBAR_ENGULFING_EMA_RSI:
            raise ValueError(
                f"Unsupported strategy type: {settings.strategy_type.value!r}"
            )
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
            require_htf_extreme_zone=settings.pier_require_htf_extreme_zone,
            htf_extreme_buffer_atr=settings.pier_htf_extreme_buffer_atr,
            strict_ema_side_rejection=settings.pier_strict_ema_side_rejection,
            min_natr_threshold=settings.pier_min_natr_threshold,
            min_sl_distance_pct=settings.pier_min_sl_distance_pct,
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
            use_structural_tp=settings.pier_use_structural_tp,
            scoring_confluence_mode=settings.pier_scoring_confluence_mode,
            use_htf_structural_tp=settings.pier_use_htf_structural_tp,
            structural_tp_buffer_pct=settings.pier_structural_tp_buffer_pct,
            min_structural_rr=settings.pier_min_structural_rr,
            bb_period=settings.pier_bb_period,
            bb_std_dev=settings.pier_bb_std_dev,
            htf_bb_period=settings.pier_htf_bb_period,
            htf_bb_std_dev=settings.pier_htf_bb_std_dev,
            use_adx_regime_filter=settings.pier_use_adx_regime_filter,
            adx_period=settings.pier_adx_period,
            adx_strong_trend_threshold=settings.pier_adx_strong_trend_threshold,
            adx_consolidation_threshold=settings.pier_adx_consolidation_threshold,
            min_tp_distance_atr=settings.pier_min_tp_distance_atr,
        )

    @staticmethod
    def create_resolver(*, settings: StrategySettings) -> StrategyResolver:
        """Register only PIER for new trading decisions."""
        strategy = StrategyFactory.create(settings=settings)
        return StrategyResolver(
            strategies={StrategyType.PINBAR_ENGULFING_EMA_RSI: strategy}
        )
