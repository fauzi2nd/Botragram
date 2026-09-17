"""
Botragram

Description:
    Environment-driven strategy-selection regression tests.

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
from decimal import Decimal
from pathlib import Path

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.environment_provider import EnvironmentProvider
from botragram.app.settings_manager import SettingsManager
from botragram.enums import Interval, StrategyType


# =============================================================================
# Test Helpers
# =============================================================================
def _create_manager(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    strategy_type: str | None,
) -> SettingsManager:
    """Create an isolated settings manager with one optional strategy value."""
    monkeypatch.delenv("BOTRAGRAM_ENV_FILE", raising=False)
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)
    if strategy_type is None:
        monkeypatch.delenv("STRATEGY_TYPE", raising=False)
    else:
        monkeypatch.setenv("STRATEGY_TYPE", strategy_type)
    return SettingsManager(
        environment_provider=EnvironmentProvider(
            env_path=str(tmp_path / "missing.env"),
        )
    )


# =============================================================================
# Strategy Environment Tests
# =============================================================================
def test_strategy_type_defaults_to_ema_cross(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve the existing EMA-cross default when the env key is absent."""
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type=None,
    )

    assert manager.load_strategy_settings().strategy_type is StrategyType.EMA_CROSS


@pytest.mark.parametrize("strategy_type", tuple(StrategyType))
def test_strategy_type_accepts_every_supported_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    strategy_type: StrategyType,
) -> None:
    """Parse every declared strategy enum through SettingsManager."""
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type=strategy_type.value,
    )

    assert manager.load_strategy_settings().strategy_type is strategy_type


def test_strategy_type_rejects_unknown_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject an unknown strategy value instead of silently using EMA cross."""
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type="unknown_strategy",
    )

    with pytest.raises(ValueError, match="STRATEGY_TYPE"):
        manager.load_strategy_settings()


def test_invert_signals_environment_setting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify INVERT_SIGNALS can be loaded as boolean."""
    monkeypatch.setenv("INVERT_SIGNALS", "true")
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type=None,
    )
    assert manager.load_strategy_settings().invert_signals is True

    monkeypatch.setenv("INVERT_SIGNALS", "false")
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type=None,
    )
    assert manager.load_strategy_settings().invert_signals is False


def test_min_signal_confidence_environment_setting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify MIN_SIGNAL_CONFIDENCE can be loaded as Decimal."""
    monkeypatch.setenv("MIN_SIGNAL_CONFIDENCE", "0.85")
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type=None,
    )
    assert manager.load_strategy_settings().min_signal_confidence == Decimal("0.85")


def test_btc_trend_environment_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify BTC_TREND_* environment variables are parsed correctly."""
    monkeypatch.setenv("BTC_TREND_FILTER_ENABLED", "true")
    monkeypatch.setenv("BTC_TREND_INTERVAL", "15m")
    monkeypatch.setenv("BTC_TREND_EMA_PERIOD", "50")
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type=None,
    )
    settings = manager.load_strategy_settings()
    assert settings.btc_trend_filter_enabled is True
    assert settings.btc_trend_interval is Interval.M15
    assert settings.btc_trend_ema_period == 50


def test_ny_range_environment_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify NY_RANGE_* environment variables are parsed correctly."""
    monkeypatch.setenv("STRATEGY_TYPE", "ny_4h_range_scalping")
    monkeypatch.setenv("NY_RANGE_RISK_REWARD_RATIO", "2.5")
    monkeypatch.setenv("NY_RANGE_MAX_SL_PCT", "0.03")
    monkeypatch.setenv("NY_RANGE_MIN_SL_PCT", "0.005")
    monkeypatch.setenv("NY_RANGE_FALLBACK_SL_PCT", "0.015")
    monkeypatch.setenv("NY_RANGE_MAX_BREAKOUT_BARS", "8")
    monkeypatch.setenv("NY_RANGE_MIN_CONFIDENCE", "0.80")
    monkeypatch.setenv("NY_RANGE_BASE_CONFIDENCE", "0.85")
    monkeypatch.setenv("NY_RANGE_USE_VOLUME_FILTER", "true")
    monkeypatch.setenv("NY_RANGE_VOLUME_PERIOD", "25")
    monkeypatch.setenv("NY_RANGE_VOLUME_MULTIPLIER", "1.5")
    monkeypatch.setenv("NY_RANGE_VOLUME_CONFIDENCE_BONUS", "0.15")
    monkeypatch.setenv("NY_RANGE_REQUIRE_VOLUME_CONFIRMATION", "true")
    monkeypatch.setenv("NY_RANGE_REQUIRE_TREND_FILTER", "false")
    monkeypatch.setenv("NY_RANGE_TREND_EMA_PERIOD", "100")
    monkeypatch.setenv("NY_RANGE_USE_RSI_FILTER", "true")
    monkeypatch.setenv("NY_RANGE_RSI_PERIOD", "21")
    monkeypatch.setenv("NY_RANGE_RSI_LONG_MAX", "50.0")
    monkeypatch.setenv("NY_RANGE_RSI_SHORT_MIN", "40.0")

    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type="ny_4h_range_scalping",
    )
    settings = manager.load_strategy_settings()
    assert settings.strategy_type is StrategyType.NY_4H_RANGE_SCALPING
    assert settings.ny_range_risk_reward_ratio == Decimal("2.5")
    assert settings.ny_range_max_sl_pct == Decimal("0.03")
    assert settings.ny_range_min_sl_pct == Decimal("0.005")
    assert settings.ny_range_fallback_sl_pct == Decimal("0.015")
    assert settings.ny_range_max_breakout_bars == 8
    assert settings.ny_range_min_confidence == Decimal("0.80")
    assert settings.ny_range_base_confidence == Decimal("0.85")
    assert settings.ny_range_use_volume_filter is True
    assert settings.ny_range_volume_period == 25
    assert settings.ny_range_volume_multiplier == Decimal("1.5")
    assert settings.ny_range_volume_confidence_bonus == Decimal("0.15")
    assert settings.ny_range_require_volume_confirmation is True
    assert settings.ny_range_require_trend_filter is False
    assert settings.ny_range_trend_ema_period == 100
    assert settings.ny_range_use_rsi_filter is True
    assert settings.ny_range_rsi_period == 21
    assert settings.ny_range_rsi_long_max == Decimal("50.0")
    assert settings.ny_range_rsi_short_min == Decimal("40.0")


def test_ny_range_environment_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify default values for NY_RANGE_* when environment variables are unset."""
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type="ny_4h_range_scalping",
    )
    settings = manager.load_strategy_settings()
    assert settings.ny_range_risk_reward_ratio == Decimal("0.8")
    assert settings.ny_range_max_sl_pct == Decimal("0.03")
    assert settings.ny_range_min_sl_pct == Decimal("0.015")
    assert settings.ny_range_fallback_sl_pct == Decimal("0.015")
    assert settings.ny_range_min_confidence == Decimal("0.75")
    assert settings.ny_range_base_confidence == Decimal("0.70")
    assert settings.ny_range_use_volume_filter is True
    assert settings.ny_range_volume_period == 20
    assert settings.ny_range_volume_multiplier == Decimal("1.0")
    assert settings.ny_range_volume_confidence_bonus == Decimal("0.10")
    assert settings.ny_range_require_volume_confirmation is False
    assert settings.ny_range_require_trend_filter is True
    assert settings.ny_range_trend_ema_period == 50
    assert settings.ny_range_use_rsi_filter is True
    assert settings.ny_range_rsi_period == 14
    assert settings.ny_range_rsi_long_max == Decimal("54.0")
    assert settings.ny_range_rsi_short_min == Decimal("44.0")


def test_origin_environment_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify all ORIGIN_* environment settings can be loaded."""
    monkeypatch.setenv("ORIGIN_RISK_REWARD_RATIO", "2.0")
    monkeypatch.setenv("ORIGIN_MIN_SL_PCT", "0.012")
    monkeypatch.setenv("ORIGIN_MAX_SL_PCT", "0.040")
    monkeypatch.setenv("ORIGIN_FALLBACK_SL_PCT", "0.020")
    monkeypatch.setenv("ORIGIN_MIN_CONFIDENCE", "0.65")
    monkeypatch.setenv("ORIGIN_USE_TREND_FILTER", "true")
    monkeypatch.setenv("ORIGIN_TREND_EMA_PERIOD", "30")
    monkeypatch.setenv("ORIGIN_USE_VOLUME_FILTER", "true")
    monkeypatch.setenv("ORIGIN_VOLUME_PERIOD", "15")
    monkeypatch.setenv("ORIGIN_VOLUME_MULTIPLIER", "1.3")
    monkeypatch.setenv("ORIGIN_USE_RSI_FILTER", "true")
    monkeypatch.setenv("ORIGIN_RSI_PERIOD", "10")
    monkeypatch.setenv("ORIGIN_RSI_LONG_MAX", "45.0")
    monkeypatch.setenv("ORIGIN_RSI_SHORT_MIN", "60.0")
    monkeypatch.setenv("ORIGIN_REQUIRE_RSI_DIRECTION", "true")
    monkeypatch.setenv("ORIGIN_USE_BB_FILTER", "true")
    monkeypatch.setenv("ORIGIN_BB_PERIOD", "25")
    monkeypatch.setenv("ORIGIN_BB_STD_DEV", "2.5")
    monkeypatch.setenv("ORIGIN_USE_MACD_FILTER", "true")
    monkeypatch.setenv("ORIGIN_MACD_FAST_PERIOD", "8")
    monkeypatch.setenv("ORIGIN_MACD_SLOW_PERIOD", "21")
    monkeypatch.setenv("ORIGIN_MACD_SIGNAL_PERIOD", "5")
    monkeypatch.setenv("ORIGIN_USE_PSAR_FILTER", "true")
    monkeypatch.setenv("ORIGIN_PSAR_MAX_PROXIMITY_PCT", "0.015")

    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type="botragram_origin",
    )
    settings = manager.load_strategy_settings()
    assert settings.origin_risk_reward_ratio == Decimal("2.0")
    assert settings.origin_min_sl_pct == Decimal("0.012")
    assert settings.origin_max_sl_pct == Decimal("0.040")
    assert settings.origin_fallback_sl_pct == Decimal("0.020")
    assert settings.origin_min_confidence == Decimal("0.65")
    assert settings.origin_use_trend_filter is True
    assert settings.origin_trend_ema_period == 30
    assert settings.origin_use_volume_filter is True
    assert settings.origin_volume_period == 15
    assert settings.origin_volume_multiplier == Decimal("1.3")
    assert settings.origin_use_rsi_filter is True
    assert settings.origin_rsi_period == 10
    assert settings.origin_rsi_long_max == Decimal("45.0")
    assert settings.origin_rsi_short_min == Decimal("60.0")
    assert settings.origin_require_rsi_direction is True
    assert settings.origin_use_bb_filter is True
    assert settings.origin_bb_period == 25
    assert settings.origin_bb_std_dev == Decimal("2.5")
    assert settings.origin_use_macd_filter is True
    assert settings.origin_macd_fast_period == 8
    assert settings.origin_macd_slow_period == 21
    assert settings.origin_macd_signal_period == 5
    assert settings.origin_use_psar_filter is True
    assert settings.origin_psar_max_proximity_pct == Decimal("0.015")


def test_origin_environment_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify default values for ORIGIN_* when environment variables are unset."""
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type="botragram_origin",
    )
    settings = manager.load_strategy_settings()
    assert settings.origin_risk_reward_ratio == Decimal("1.5")
    assert settings.origin_min_sl_pct == Decimal("0.010")
    assert settings.origin_max_sl_pct == Decimal("0.030")
    assert settings.origin_fallback_sl_pct == Decimal("0.015")
    assert settings.origin_min_confidence == Decimal("0.70")
    assert settings.origin_use_trend_filter is False
    assert settings.origin_trend_ema_period == 50
    assert settings.origin_use_volume_filter is False
    assert settings.origin_volume_period == 20
    assert settings.origin_volume_multiplier == Decimal("1.0")
    assert settings.origin_use_rsi_filter is False
    assert settings.origin_rsi_period == 14
    assert settings.origin_rsi_long_max == Decimal("70.0")
    assert settings.origin_rsi_short_min == Decimal("30.0")
    assert settings.origin_require_rsi_direction is False
    assert settings.origin_use_bb_filter is False
    assert settings.origin_bb_period == 20
    assert settings.origin_bb_std_dev == Decimal("2.0")
    assert settings.origin_use_macd_filter is False
    assert settings.origin_macd_fast_period == 12
    assert settings.origin_macd_slow_period == 26
    assert settings.origin_macd_signal_period == 9
    assert settings.origin_use_psar_filter is False
    assert settings.origin_psar_max_proximity_pct == Decimal("0.008")
