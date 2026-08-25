"""Settings safety tests for isolated LIVE deployments."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from botragram.app import SettingsManager
from botragram.app.environment_provider import EnvironmentProvider
from botragram.config.risk_settings import RiskSettings
from botragram.enums import ExchangeEnvironment


@pytest.mark.parametrize(
    ("testnet", "expected_environment"),
    ((True, ExchangeEnvironment.TESTNET), (False, ExchangeEnvironment.MAINNET)),
)
def test_live_settings_scope_database_by_venue_network(
    testnet: bool,
    expected_environment: ExchangeEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep every LIVE venue network on a separate durable SQLite file."""
    monkeypatch.setenv("TRADE_MODE", "live")
    monkeypatch.setenv("ACTIVE_EXCHANGE", "binance")
    monkeypatch.setenv("BINANCE_MARKET_TYPE", "futures")
    monkeypatch.setenv("BINANCE_TESTNET", str(testnet).lower())
    monkeypatch.setenv("BINANCE_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "test-secret")
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)

    settings = SettingsManager(
        environment_provider=EnvironmentProvider(env_path=str(tmp_path / "missing.env"))
    ).load()

    assert settings.exchange.environment is expected_environment
    assert settings.app.database_path == Path(
        f"data/botragram-binance-futures-{expected_environment.value}.db"
    )


def test_risk_settings_load_execution_quality_limits_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load explicit sizing, drawdown, and executable-quote risk limits."""
    monkeypatch.setenv("RISK_PER_TRADE_PCT", "0.015")
    monkeypatch.setenv("MAX_DRAWDOWN_PCT", "0.08")
    monkeypatch.setenv("LEVERAGE", "3")
    monkeypatch.setenv("MAX_EXECUTABLE_QUOTE_AGE_MS", "750")
    monkeypatch.setenv("MAX_SPREAD_BPS", "12.5")
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)

    risk = SettingsManager(
        environment_provider=EnvironmentProvider(env_path=str(tmp_path / "missing.env"))
    ).load_risk_settings()

    assert risk.risk_per_trade_pct == Decimal("0.015")
    assert risk.max_drawdown_pct == Decimal("0.08")
    assert risk.leverage == 3
    assert risk.max_executable_quote_age_ms == 750
    assert risk.max_spread_bps == Decimal("12.5")


@pytest.mark.parametrize("value", (Decimal("NaN"), Decimal("Infinity"), Decimal("0")))
def test_risk_settings_reject_invalid_executable_spread_limit(value: Decimal) -> None:
    """Fail closed when direct configuration cannot bound MARKET spread."""
    with pytest.raises(ValueError, match="Maximum spread"):
        RiskSettings(max_spread_bps=value)
