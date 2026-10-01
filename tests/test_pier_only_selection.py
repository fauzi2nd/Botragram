"""Regression coverage for the PIER-only active strategy boundary."""

from collections.abc import Callable
from decimal import Decimal

import pytest

from botragram.config.strategy_settings import StrategySettings
from botragram.enums import StrategyType
from botragram.strategies.factory import StrategyFactory
from botragram.strategies.price_action import PinbarEngulfingEmaRsiStrategy

__all__ = []


def test_factory_registers_only_pier() -> None:
    """The active resolver must expose only the retained strategy."""
    resolver = StrategyFactory.create_resolver(settings=StrategySettings())

    assert set(resolver.strategies) == {StrategyType.PINBAR_ENGULFING_EMA_RSI}
    assert isinstance(
        resolver.resolve(strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI),
        PinbarEngulfingEmaRsiStrategy,
    )


@pytest.mark.parametrize(
    "strategy_type",
    [
        strategy_type
        for strategy_type in StrategyType
        if strategy_type is not StrategyType.PINBAR_ENGULFING_EMA_RSI
    ],
)
def test_factory_rejects_every_legacy_strategy(strategy_type: StrategyType) -> None:
    """Historical identifiers cannot instantiate new trading strategies."""
    with pytest.raises(ValueError, match="Unsupported strategy type"):
        StrategyFactory.create(settings=StrategySettings(strategy_type=strategy_type))


@pytest.mark.parametrize(
    "settings_factory",
    [
        pytest.param(
            lambda: StrategySettings(pier_trend_period=0), id="pier_trend_period"
        ),
        pytest.param(
            lambda: StrategySettings(pier_pullback_period=200),
            id="pier_pullback_period",
        ),
        pytest.param(lambda: StrategySettings(pier_rsi_period=0), id="pier_rsi_period"),
        pytest.param(
            lambda: StrategySettings(pier_rsi_long_min=Decimal("101")),
            id="pier_rsi_long_min",
        ),
        pytest.param(
            lambda: StrategySettings(pier_rsi_short_min=Decimal("101")),
            id="pier_rsi_short_min",
        ),
        pytest.param(
            lambda: StrategySettings(pier_volume_period=0), id="pier_volume_period"
        ),
        pytest.param(
            lambda: StrategySettings(pier_min_wick_ratio=Decimal("0")),
            id="pier_min_wick_ratio",
        ),
        pytest.param(
            lambda: StrategySettings(pier_max_opposite_wick_ratio=Decimal("2")),
            id="pier_max_opposite_wick_ratio",
        ),
        pytest.param(
            lambda: StrategySettings(pier_min_engulfing_body_ratio=Decimal("0")),
            id="pier_min_engulfing_body_ratio",
        ),
        pytest.param(
            lambda: StrategySettings(pier_atr_sl_multiplier=Decimal("0")),
            id="pier_atr_sl_multiplier",
        ),
        pytest.param(
            lambda: StrategySettings(pier_min_confidence=Decimal("2")),
            id="pier_min_confidence",
        ),
        pytest.param(
            lambda: StrategySettings(min_oi_change_pct=Decimal("-1")),
            id="min_oi_change_pct",
        ),
        pytest.param(
            lambda: StrategySettings(pier_htf_extreme_buffer_atr=Decimal("-1")),
            id="pier_htf_extreme_buffer_atr",
        ),
        pytest.param(
            lambda: StrategySettings(pier_stalking_max_bars=0),
            id="pier_stalking_max_bars",
        ),
        pytest.param(
            lambda: StrategySettings(pier_stalking_max_candidates=0),
            id="pier_stalking_max_candidates",
        ),
        pytest.param(
            lambda: StrategySettings(pier_stalking_retest_ratio=Decimal("2")),
            id="pier_stalking_retest_ratio",
        ),
        pytest.param(
            lambda: StrategySettings(pier_min_natr_threshold=Decimal("-1")),
            id="pier_min_natr_threshold",
        ),
        pytest.param(
            lambda: StrategySettings(pier_min_sl_distance_pct=Decimal("-1")),
            id="pier_min_sl_distance_pct",
        ),
        pytest.param(
            lambda: StrategySettings(pier_location_tolerance_pct=Decimal("-1")),
            id="pier_location_tolerance_pct",
        ),
        pytest.param(
            lambda: StrategySettings(pier_location_atr_multiplier=Decimal("0")),
            id="pier_location_atr_multiplier",
        ),
        pytest.param(
            lambda: StrategySettings(pier_pullback_proximity_pct=Decimal("-1")),
            id="pier_pullback_proximity_pct",
        ),
        pytest.param(
            lambda: StrategySettings(pier_pullback_atr_multiplier=Decimal("0")),
            id="pier_pullback_atr_multiplier",
        ),
        pytest.param(
            lambda: StrategySettings(pier_pinbar_min_range_atr=Decimal("0")),
            id="pier_pinbar_min_range_atr",
        ),
        pytest.param(
            lambda: StrategySettings(pier_engulfing_min_body_atr=Decimal("0")),
            id="pier_engulfing_min_body_atr",
        ),
        pytest.param(
            lambda: StrategySettings(pier_macd_fast_period=0),
            id="pier_macd_fast_period",
        ),
        pytest.param(
            lambda: StrategySettings(pier_stoch_rsi_period=0),
            id="pier_stoch_rsi_period",
        ),
        pytest.param(
            lambda: StrategySettings(pier_stoch_rsi_oversold=Decimal("101")),
            id="pier_stoch_rsi_oversold",
        ),
        pytest.param(
            lambda: StrategySettings(pier_structural_tp_buffer_pct=Decimal("-1")),
            id="pier_structural_tp_buffer_pct",
        ),
        pytest.param(
            lambda: StrategySettings(pier_min_structural_rr=Decimal("0")),
            id="pier_min_structural_rr",
        ),
        pytest.param(lambda: StrategySettings(pier_bb_period=0), id="pier_bb_period"),
        pytest.param(
            lambda: StrategySettings(pier_htf_bb_period=0), id="pier_htf_bb_period"
        ),
    ],
)
def test_pier_settings_reject_invalid_parameters(
    settings_factory: Callable[[], StrategySettings],
) -> None:
    """Reject invalid PIER parameters before constructing a trading strategy."""
    with pytest.raises(ValueError):
        settings_factory()


@pytest.mark.parametrize(
    "settings_factory",
    [
        pytest.param(
            lambda: StrategySettings(choch_swing_window=0), id="choch_swing_window"
        ),
        pytest.param(
            lambda: StrategySettings(choch_volume_period=0), id="choch_volume_period"
        ),
        pytest.param(
            lambda: StrategySettings(choch_min_body_ratio=Decimal("0")),
            id="choch_min_body_ratio",
        ),
        pytest.param(
            lambda: StrategySettings(choch_min_gap_ratio=Decimal("-1")),
            id="choch_min_gap_ratio",
        ),
        pytest.param(
            lambda: StrategySettings(choch_trend_period=0), id="choch_trend_period"
        ),
        pytest.param(
            lambda: StrategySettings(choch_intermediate_trend_period=1000),
            id="choch_intermediate_trend_period",
        ),
        pytest.param(
            lambda: StrategySettings(choch_min_confidence=Decimal("2")),
            id="choch_min_confidence",
        ),
        pytest.param(lambda: StrategySettings(hce_bb_period=0), id="hce_bb_period"),
        pytest.param(
            lambda: StrategySettings(hce_bb_std_dev=Decimal("0")), id="hce_bb_std_dev"
        ),
        pytest.param(lambda: StrategySettings(hce_rsi_period=0), id="hce_rsi_period"),
        pytest.param(
            lambda: StrategySettings(hce_rsi_oversold=Decimal("101")),
            id="hce_rsi_oversold",
        ),
        pytest.param(
            lambda: StrategySettings(hce_volume_period=0), id="hce_volume_period"
        ),
        pytest.param(lambda: StrategySettings(hce_adx_period=0), id="hce_adx_period"),
        pytest.param(
            lambda: StrategySettings(hce_trend_period=0), id="hce_trend_period"
        ),
        pytest.param(
            lambda: StrategySettings(hce_intermediate_trend_period=0),
            id="hce_intermediate_trend_period",
        ),
        pytest.param(
            lambda: StrategySettings(crbb_swing_window=0), id="crbb_swing_window"
        ),
        pytest.param(
            lambda: StrategySettings(crbb_volume_period=0), id="crbb_volume_period"
        ),
        pytest.param(
            lambda: StrategySettings(crbb_min_gap_ratio=Decimal("-1")),
            id="crbb_min_gap_ratio",
        ),
        pytest.param(
            lambda: StrategySettings(crbb_trend_period=0), id="crbb_trend_period"
        ),
        pytest.param(
            lambda: StrategySettings(crbb_intermediate_trend_period=1000),
            id="crbb_intermediate_trend_period",
        ),
        pytest.param(lambda: StrategySettings(crbb_bb_period=0), id="crbb_bb_period"),
        pytest.param(lambda: StrategySettings(crbb_rsi_period=0), id="crbb_rsi_period"),
        pytest.param(
            lambda: StrategySettings(crbb_rsi_oversold=Decimal("101")),
            id="crbb_rsi_oversold",
        ),
        pytest.param(lambda: StrategySettings(crbb_adx_period=0), id="crbb_adx_period"),
        pytest.param(lambda: StrategySettings(crbb_atr_period=0), id="crbb_atr_period"),
        pytest.param(
            lambda: StrategySettings(crbb_min_wick_ratio=Decimal("-1")),
            id="crbb_min_wick_ratio",
        ),
        pytest.param(
            lambda: StrategySettings(crbb_min_confidence=Decimal("2")),
            id="crbb_min_confidence",
        ),
        pytest.param(
            lambda: StrategySettings(crbb_cooldown_bars=-1), id="crbb_cooldown_bars"
        ),
        pytest.param(
            lambda: StrategySettings(crbb_max_hold_bars=0), id="crbb_max_hold_bars"
        ),
        pytest.param(
            lambda: StrategySettings(crbb_short_bias_multiplier=Decimal("0")),
            id="crbb_short_bias_multiplier",
        ),
        pytest.param(
            lambda: StrategySettings(lse_swing_lookback=0), id="lse_swing_lookback"
        ),
        pytest.param(
            lambda: StrategySettings(lse_min_wick_ratio=Decimal("0")),
            id="lse_min_wick_ratio",
        ),
        pytest.param(
            lambda: StrategySettings(lse_volume_period=0), id="lse_volume_period"
        ),
        pytest.param(lambda: StrategySettings(lse_rsi_period=0), id="lse_rsi_period"),
        pytest.param(
            lambda: StrategySettings(lse_rsi_oversold=Decimal("101")),
            id="lse_rsi_oversold",
        ),
        pytest.param(lambda: StrategySettings(lse_atr_period=0), id="lse_atr_period"),
        pytest.param(
            lambda: StrategySettings(lse_atr_multiplier_sl=Decimal("0")),
            id="lse_atr_multiplier_sl",
        ),
        pytest.param(
            lambda: StrategySettings(lse_min_natr_threshold=Decimal("-1")),
            id="lse_min_natr_threshold",
        ),
        pytest.param(
            lambda: StrategySettings(lse_funding_buffer_minutes=-1),
            id="lse_funding_buffer_minutes",
        ),
        pytest.param(
            lambda: StrategySettings(lse_min_confidence=Decimal("2")),
            id="lse_min_confidence",
        ),
        pytest.param(
            lambda: StrategySettings(lse_cooldown_bars=-1), id="lse_cooldown_bars"
        ),
        pytest.param(
            lambda: StrategySettings(lse_max_hold_bars=0), id="lse_max_hold_bars"
        ),
        pytest.param(
            lambda: StrategySettings(lse_short_bias_multiplier=Decimal("0")),
            id="lse_short_bias_multiplier",
        ),
        pytest.param(
            lambda: StrategySettings(scalping_fast_period=0), id="scalping_fast_period"
        ),
        pytest.param(
            lambda: StrategySettings(scalping_minimum_body_ratio=Decimal("2")),
            id="scalping_minimum_body_ratio",
        ),
        pytest.param(
            lambda: StrategySettings(scalping_trend_period=0),
            id="scalping_trend_period",
        ),
        pytest.param(lambda: StrategySettings(quad_rsi_period=0), id="quad_rsi_period"),
        pytest.param(
            lambda: StrategySettings(quad_stoch_oversold=Decimal("101")),
            id="quad_stoch_oversold",
        ),
        pytest.param(lambda: StrategySettings(quad_bb_period=0), id="quad_bb_period"),
        pytest.param(
            lambda: StrategySettings(quad_sar_step=Decimal("0")), id="quad_sar_step"
        ),
    ],
)
def test_legacy_settings_remain_safely_validated(
    settings_factory: Callable[[], StrategySettings],
) -> None:
    """Historical configuration fields remain bounded while records are readable."""
    with pytest.raises(ValueError):
        settings_factory()
