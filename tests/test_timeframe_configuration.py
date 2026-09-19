"""
Botragram

Description:
    Regression tests for timeframe configuration hierarchy and resolution precedence.

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
import logging
from pathlib import Path

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.backtest_command import parse_backtest_request
from botragram.app.environment_provider import EnvironmentProvider
from botragram.app.settings_manager import SettingsManager
from botragram.enums import Interval


# =============================================================================
# Test Helpers
# =============================================================================
def _create_isolated_settings_manager(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env_vars: dict[str, str],
) -> SettingsManager:
    """Create an isolated SettingsManager with clean test environment."""
    monkeypatch.delenv("BOTRAGRAM_ENV_FILE", raising=False)
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)
    monkeypatch.delenv("GLOBAL_MARKET_INTERVAL", raising=False)
    monkeypatch.delenv("MARKET_INTERVAL", raising=False)
    monkeypatch.delenv("STRATEGY_TIMEFRAME_OVERRIDE_ENABLED", raising=False)
    monkeypatch.delenv("STRATEGY_TIMEFRAME_OVERRIDE", raising=False)
    monkeypatch.delenv("MTF_CONFIRMATION_ENABLED", raising=False)
    monkeypatch.delenv("MTF_TIMEFRAME", raising=False)

    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)

    return SettingsManager(
        environment_provider=EnvironmentProvider(
            env_path=str(tmp_path / "empty.env"),
        )
    )


# =============================================================================
# Tests
# =============================================================================
def test_case_a_global_only_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Case A: Global only, override disabled -> effective=5m, source=global."""
    manager = _create_isolated_settings_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env_vars={
            "GLOBAL_MARKET_INTERVAL": "5m",
            "STRATEGY_TIMEFRAME_OVERRIDE_ENABLED": "false",
        },
    )
    settings = manager.load()

    assert settings.market.interval is Interval.M5
    assert settings.market.global_interval is Interval.M5
    assert not settings.strategy.timeframe_override_enabled
    assert settings.effective_strategy_interval is Interval.M5
    assert settings.strategy_interval_source == "global"


def test_case_b_strategy_override_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Case B: Strategy override enabled -> effective=3m, source=override."""
    manager = _create_isolated_settings_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env_vars={
            "GLOBAL_MARKET_INTERVAL": "5m",
            "STRATEGY_TIMEFRAME_OVERRIDE_ENABLED": "true",
            "STRATEGY_TIMEFRAME_OVERRIDE": "3m",
        },
    )
    settings = manager.load()

    assert settings.market.interval is Interval.M5
    assert settings.strategy.timeframe_override_enabled
    assert settings.strategy.timeframe_override is Interval.M3
    assert settings.effective_strategy_interval is Interval.M3
    assert settings.strategy_interval_source == "override"


def test_case_c_override_invalid_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Case C: Override enabled with invalid interval value -> fail closed."""
    manager = _create_isolated_settings_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env_vars={
            "GLOBAL_MARKET_INTERVAL": "5m",
            "STRATEGY_TIMEFRAME_OVERRIDE_ENABLED": "true",
            "STRATEGY_TIMEFRAME_OVERRIDE": "abc",
        },
    )
    with pytest.raises(ValueError, match="STRATEGY_TIMEFRAME_OVERRIDE"):
        manager.load()


def test_case_d_override_enabled_but_empty_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Case D: Override enabled but empty -> fail closed."""
    manager = _create_isolated_settings_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env_vars={
            "GLOBAL_MARKET_INTERVAL": "5m",
            "STRATEGY_TIMEFRAME_OVERRIDE_ENABLED": "true",
            "STRATEGY_TIMEFRAME_OVERRIDE": "",
        },
    )
    with pytest.raises(ValueError, match="cannot be empty"):
        manager.load()


def test_case_e_mtf_independent_from_strategy_tf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Case E: MTF confirmation TF is strictly isolated from strategy and global TF."""
    manager = _create_isolated_settings_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env_vars={
            "GLOBAL_MARKET_INTERVAL": "5m",
            "STRATEGY_TIMEFRAME_OVERRIDE_ENABLED": "true",
            "STRATEGY_TIMEFRAME_OVERRIDE": "3m",
            "MTF_CONFIRMATION_ENABLED": "true",
            "MTF_TIMEFRAME": "15m",
        },
    )
    settings = manager.load()

    assert settings.market.interval is Interval.M5
    assert settings.effective_strategy_interval is Interval.M3
    assert settings.strategy.mtf_confirmation_enabled
    assert settings.strategy.mtf_interval is Interval.M15
    assert settings.strategy_interval_source == "override"


def test_case_f_legacy_market_interval_backward_compatibility(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Case F: Legacy MARKET_INTERVAL logs warning and respects precedence."""
    # 1. Legacy MARKET_INTERVAL alone
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        manager_legacy = _create_isolated_settings_manager(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            env_vars={
                "MARKET_INTERVAL": "5m",
                "STRATEGY_TIMEFRAME_OVERRIDE_ENABLED": "false",
            },
        )
        settings_legacy = manager_legacy.load()

    assert settings_legacy.market.interval is Interval.M5
    assert settings_legacy.effective_strategy_interval is Interval.M5
    assert any("MARKET_INTERVAL' is deprecated" in r.message for r in caplog.records)

    # 2. GLOBAL_MARKET_INTERVAL overrides legacy MARKET_INTERVAL without warning
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        manager_both = _create_isolated_settings_manager(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            env_vars={
                "GLOBAL_MARKET_INTERVAL": "15m",
                "MARKET_INTERVAL": "5m",
            },
        )
        settings_both = manager_both.load()

    assert settings_both.market.interval is Interval.M15
    assert not any(
        "MARKET_INTERVAL' is deprecated" in r.message for r in caplog.records
    )


def test_case_g_explicit_cli_backtest_interval_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Case G: Explicit CLI backtest interval takes precedence over .env override."""
    manager = _create_isolated_settings_manager(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env_vars={
            "GLOBAL_MARKET_INTERVAL": "5m",
            "STRATEGY_TIMEFRAME_OVERRIDE_ENABLED": "true",
            "STRATEGY_TIMEFRAME_OVERRIDE": "3m",
        },
    )
    settings = manager.load()
    assert settings.effective_strategy_interval is Interval.M3

    # 1. Explicit CLI --interval 15m should NOT be overridden by .env 3m
    cli_args_explicit = (
        "backtest",
        "--market-type",
        "futures",
        "--symbol",
        "BTCUSDT",
        "--strategy",
        "botragram_origin",
        "--interval",
        "15m",
        "--start",
        "2026-01-01",
        "--end",
        "2026-01-02",
    )
    request_explicit = parse_backtest_request(
        arguments=cli_args_explicit,
        default_interval=settings.effective_strategy_interval,
    )
    assert request_explicit.interval is Interval.M15

    # 2. Omitted CLI --interval should fall back to default_interval (effective 3m)
    cli_args_omitted = (
        "backtest",
        "--market-type",
        "futures",
        "--symbol",
        "BTCUSDT",
        "--strategy",
        "botragram_origin",
        "--start",
        "2026-01-01",
        "--end",
        "2026-01-02",
    )
    request_omitted = parse_backtest_request(
        arguments=cli_args_omitted,
        default_interval=settings.effective_strategy_interval,
    )
    assert request_omitted.interval is Interval.M3
