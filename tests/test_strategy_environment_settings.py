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
from botragram.enums import StrategyType


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
