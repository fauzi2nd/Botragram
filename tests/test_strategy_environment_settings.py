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
from botragram.app.settings.environment_provider import EnvironmentProvider
from botragram.app.settings.settings_manager import SettingsManager
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
def test_strategy_type_defaults_to_pier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Use PIER when the strategy environment key is absent."""
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type=None,
    )

    assert (
        manager.load_strategy_settings().strategy_type
        is StrategyType.PINBAR_ENGULFING_EMA_RSI
    )


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    (("", None), (" 15m ", Interval.M15)),
)
def test_optional_timeframe_override_preserves_disabled_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_value: str,
    expected: Interval | None,
) -> None:
    """Parse a supplied override even when its activation flag is disabled."""
    monkeypatch.setenv("STRATEGY_TIMEFRAME_OVERRIDE_ENABLED", "false")
    monkeypatch.setenv("STRATEGY_TIMEFRAME_OVERRIDE", raw_value)
    manager = _create_manager(
        monkeypatch=monkeypatch, tmp_path=tmp_path, strategy_type=None
    )

    assert manager.load_strategy_settings().timeframe_override is expected


def test_strategy_type_accepts_pier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Accept the sole active strategy identifier."""
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
    )
    assert (
        manager.load_strategy_settings().strategy_type
        is StrategyType.PINBAR_ENGULFING_EMA_RSI
    )


@pytest.mark.parametrize(
    "strategy_type",
    tuple(
        strategy_type
        for strategy_type in StrategyType
        if strategy_type is not StrategyType.PINBAR_ENGULFING_EMA_RSI
    ),
)
def test_strategy_type_rejects_legacy_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    strategy_type: StrategyType,
) -> None:
    """Keep legacy identifiers readable but unavailable for new selection."""
    manager = _create_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        strategy_type=strategy_type.value,
    )
    with pytest.raises(ValueError, match="Only PIER"):
        manager.load_strategy_settings()


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
