"""Settings safety tests for isolated LIVE deployments."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from botragram.app import SettingsManager
from botragram.app.environment_provider import EnvironmentProvider
from botragram.config.risk_settings import RiskSettings
from botragram.enums import ExchangeEnvironment
from botragram.models import AutonomousLiveEntryAuthorization


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
    monkeypatch.setenv("EXECUTION_POLICY", "single_symbol")
    monkeypatch.setenv("AUTONOMOUS_EXECUTION_ENABLED", "false")
    monkeypatch.setenv("AUTONOMOUS_LIVE_ENTRY_ENABLED", "false")
    monkeypatch.setenv("AUTONOMOUS_MAINNET_ENTRY_ENABLED", "false")
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


def test_live_settings_scope_database_by_bybit_demo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep Bybit DEMO network on a separate durable SQLite file."""
    monkeypatch.setenv("TRADE_MODE", "live")
    monkeypatch.setenv("ACTIVE_EXCHANGE", "bybit")
    monkeypatch.setenv("BYBIT_MARKET_TYPE", "futures")
    monkeypatch.setenv("BYBIT_TESTNET", "false")
    monkeypatch.setenv("BYBIT_DEMO", "true")
    monkeypatch.setenv("BYBIT_API_KEY", "demo-key")
    monkeypatch.setenv("BYBIT_API_SECRET", "demo-secret")
    monkeypatch.setenv("EXECUTION_POLICY", "single_symbol")
    monkeypatch.setenv("AUTONOMOUS_EXECUTION_ENABLED", "false")
    monkeypatch.setenv("AUTONOMOUS_LIVE_ENTRY_ENABLED", "false")
    monkeypatch.setenv("AUTONOMOUS_MAINNET_ENTRY_ENABLED", "false")
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)

    settings = SettingsManager(
        environment_provider=EnvironmentProvider(env_path=str(tmp_path / "missing.env"))
    ).load()

    assert settings.exchange.environment is ExchangeEnvironment.DEMO
    assert settings.app.database_path == Path("data/botragram-bybit-futures-demo.db")


def test_autonomous_live_entry_authorization_rejects_demo_with_mainnet_opt_in() -> None:
    """Ensure DEMO environment rejects MAINNET opt-in."""
    with pytest.raises(
        ValueError, match="MAINNET entry opt-in requires MAINNET environment"
    ):
        AutonomousLiveEntryAuthorization(
            environment=ExchangeEnvironment.DEMO,
            explicit_opt_in=True,
            mainnet_explicit_opt_in=True,
        )


def test_bybit_settings_reject_both_testnet_and_demo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail closed when both BYBIT_TESTNET and BYBIT_DEMO are true."""
    monkeypatch.setenv("ACTIVE_EXCHANGE", "bybit")
    monkeypatch.setenv("BYBIT_MARKET_TYPE", "futures")
    monkeypatch.setenv("BYBIT_TESTNET", "true")
    monkeypatch.setenv("BYBIT_DEMO", "true")
    monkeypatch.setenv("BYBIT_API_KEY", "key")
    monkeypatch.setenv("BYBIT_API_SECRET", "secret")
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)

    with pytest.raises(ValueError, match="cannot enable both testnet and demo"):
        SettingsManager(
            environment_provider=EnvironmentProvider(
                env_path=str(tmp_path / "missing.env")
            )
        ).load_exchange_settings()


def test_market_settings_load_discovery_candle_delay_seconds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load and validate DISCOVERY_CANDLE_DELAY_SECONDS from environment."""
    monkeypatch.setenv("DISCOVERY_CANDLE_DELAY_SECONDS", "0.1")
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)
    market = SettingsManager(
        environment_provider=EnvironmentProvider(env_path=str(tmp_path / "missing.env"))
    ).load_market_settings()
    assert market.discovery_candle_delay_seconds == 0.1
