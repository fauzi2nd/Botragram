"""
Botragram

Description:
    Foundation, configuration, environment, and utility tests.

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
import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import DependencyProvider, SettingsManager
from botragram.app.environment_provider import EnvironmentProvider
from botragram.config import Settings
from botragram.config.app_settings import AppSettings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.config.market_settings import MarketSettings
from botragram.config.risk_settings import RiskSettings
from botragram.enums import (
    Environment,
    EnvironmentProfile,
    ExchangeEnvironment,
    ExchangeType,
    ExecutionPolicy,
    Interval,
    LogLevel,
    MarketType,
    StrategyType,
    TradeMode,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePositionContext,
)
from botragram.utils.datetime import (
    current_utc_timestamp_ms,
    format_utc_datetime,
    timestamp_ms_to_datetime,
)
from botragram.utils.decimal import (
    round_price_precision,
    round_step_size,
    to_decimal,
)
from botragram.utils.formatter import (
    format_currency,
    format_percentage,
    format_price,
)
from botragram.utils.validator import validate_positive_decimal, validate_symbol

# =============================================================================
# Constants
# =============================================================================
_ENVIRONMENT_KEYS = (
    "ACTIVE_EXCHANGE",
    "AUTONOMOUS_EXECUTION_ENABLED",
    "AUTONOMOUS_LIVE_ENTRY_ENABLED",
    "AUTONOMOUS_MAINNET_ENTRY_ENABLED",
    "AI_MODEL",
    "AI_PROVIDER",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_MARKET_TYPE",
    "BINANCE_TESTNET",
    "BOTRAGRAM_ENV_FILE",
    "BOTRAGRAM_PROFILE",
    "BOTRAGRAM_EXCHANGE_API_KEY",
    "BOTRAGRAM_EXCHANGE_API_SECRET",
    "BOTRAGRAM_LOG_LEVEL",
    "BOTRAGRAM_TELEGRAM_TOKEN",
    "BOTRAGRAM_TRADE_MODE",
    "EMA_CROSS_STOP_LOSS_PCT",
    "EMA_CROSS_TAKE_PROFIT_PCT",
    "EMA_SCALPING_STOP_LOSS_PCT",
    "EMA_SCALPING_TAKE_PROFIT_PCT",
    "SCALPING_STOP_LOSS_PCT",
    "SCALPING_TAKE_PROFIT_PCT",
    "TREND_STOP_LOSS_PCT",
    "TREND_TAKE_PROFIT_PCT",
    "SWING_STOP_LOSS_PCT",
    "SWING_TAKE_PROFIT_PCT",
    "STOP_LOSS_PCT",
    "TAKE_PROFIT_PCT",
    "DISCOVERY_BATCH_SIZE",
    "DISCOVERY_CADENCE_SECONDS",
    "DISCOVERY_UNIVERSE_LIMIT",
    "EXECUTION_POLICY",
    "GEMINI_API_KEY",
    "LOG_LEVEL",
    "MAX_OPEN_POSITIONS",
    "MAX_POSITION_SIZE_USDT",
    "MARKET_INTERVAL",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "STRATEGY_TYPE",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_TOKEN",
    "TRADE_MODE",
)


# =============================================================================
# Test Helpers
# =============================================================================
def _create_environment_provider(
    *,
    monkeypatch: pytest.MonkeyPatch,
    temporary_path: Path,
) -> EnvironmentProvider:
    """Create an isolated environment provider without loading project dotenv."""
    _clear_environment(monkeypatch)

    return EnvironmentProvider(
        env_path=str(temporary_path / "missing.env"),
    )


def _clear_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove configuration values while preserving test cleanup."""
    for key in _ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)


def _write_environment_file(path: Path, content: str) -> None:
    """Write one isolated dotenv test fixture."""
    path.write_text(content, encoding="utf-8")


# =============================================================================
# Configuration Tests
# =============================================================================
def test_configuration_defaults_are_safe_and_immutable() -> None:
    """Verify default settings favor paper trading and testnet."""
    settings = Settings()

    assert settings.app.trade_mode is TradeMode.PAPER
    assert not settings.app.autonomous_execution_enabled
    assert not settings.app.autonomous_live_entry_enabled
    assert settings.exchange.exchange is ExchangeType.BINANCE
    assert settings.exchange.testnet
    assert not settings.exchange.is_live
    assert settings.market.symbol == "BTCUSDT"
    assert settings.market.discovery_max_symbols == 20
    assert settings.market.discovery_universe_limit == 100
    assert settings.market.discovery_batch_size == 20
    assert settings.market.discovery_top_n == 5
    assert settings.market.discovery_cadence_seconds is None
    assert settings.app.database_path == Path("data") / "botragram.db"

    with pytest.raises(FrozenInstanceError):
        setattr(settings.app, "trade_mode", TradeMode.LIVE)


def test_app_debug_mode_depends_on_environment() -> None:
    """Verify debug mode is limited to development and testing."""
    assert AppSettings(environment=Environment.DEVELOPMENT).debug
    assert AppSettings(environment=Environment.TESTING).debug
    assert not AppSettings(environment=Environment.STAGING).debug
    assert not AppSettings(environment=Environment.PRODUCTION).debug


def test_market_symbol_combines_configured_assets() -> None:
    """Verify market settings expose the configured trading symbol."""
    settings = MarketSettings(base_asset="ETH", quote_asset="USDC")

    assert settings.symbol == "ETHUSDC"


@pytest.mark.parametrize(
    ("raw_interval", "expected"),
    (("1m", Interval.M1), ("1M", Interval.MN1), ("", Interval.M15)),
)
def test_settings_manager_loads_configured_market_interval(
    raw_interval: str,
    expected: Interval,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load an explicit supported interval and preserve the unset default."""
    _clear_environment(monkeypatch)
    path = tmp_path / ".env"
    _write_environment_file(path, f"MARKET_INTERVAL={raw_interval}\n")

    settings = SettingsManager(
        environment_provider=EnvironmentProvider(env_path=str(path))
    ).load()

    assert settings.market.interval is expected


def test_settings_manager_rejects_invalid_market_interval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject an unsupported timeframe without silently changing cadence."""
    _clear_environment(monkeypatch)
    path = tmp_path / ".env"
    _write_environment_file(path, "MARKET_INTERVAL=30s\n")

    with pytest.raises(ValueError, match="MARKET_INTERVAL"):
        SettingsManager(
            environment_provider=EnvironmentProvider(env_path=str(path))
        ).load()


def test_settings_manager_loads_ranked_discovery_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load explicit universe, batch, and autonomous global cadence values."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("DISCOVERY_UNIVERSE_LIMIT", "47")
    monkeypatch.setenv("DISCOVERY_BATCH_SIZE", "7")
    monkeypatch.setenv("DISCOVERY_CADENCE_SECONDS", "10")

    settings = SettingsManager(environment_provider=provider).load_market_settings()

    assert settings.discovery_universe_limit == 47
    assert settings.discovery_batch_size == 7
    assert settings.discovery_top_n == 5
    assert settings.discovery_cadence_seconds == 10
    assert settings.discovery_max_symbols == 20


@pytest.mark.parametrize(
    ("setting_name", "raw_value"),
    (
        ("DISCOVERY_UNIVERSE_LIMIT", "0"),
        ("DISCOVERY_UNIVERSE_LIMIT", "-1"),
        ("DISCOVERY_UNIVERSE_LIMIT", "many"),
        ("DISCOVERY_BATCH_SIZE", "0"),
        ("DISCOVERY_BATCH_SIZE", "-1"),
        ("DISCOVERY_BATCH_SIZE", "many"),
        ("DISCOVERY_CADENCE_SECONDS", "0"),
        ("DISCOVERY_CADENCE_SECONDS", "-1"),
        ("DISCOVERY_CADENCE_SECONDS", "often"),
    ),
)
def test_settings_manager_rejects_invalid_ranked_discovery_integers(
    setting_name: str,
    raw_value: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject zero, negative, and non-integer ranked discovery values."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv(setting_name, raw_value)

    with pytest.raises(ValueError, match=setting_name):
        SettingsManager(environment_provider=provider).load_market_settings()


def test_market_settings_preserves_legacy_top_n_independence_from_live_batch() -> None:
    """Keep legacy discovery_top_n independent from autonomous LIVE batch policy."""
    settings = MarketSettings(
        discovery_universe_limit=10,
        discovery_batch_size=5,
        discovery_top_n=6,
    )

    assert settings.discovery_top_n == 6
    assert settings.discovery_batch_size == 5


def test_market_settings_rejects_batch_larger_than_ranked_universe() -> None:
    """Require the autonomous ranked batch to fit inside its universe limit."""
    with pytest.raises(ValueError, match="batch size must not exceed universe"):
        MarketSettings(
            discovery_universe_limit=4,
            discovery_batch_size=5,
            discovery_top_n=4,
        )


@pytest.mark.parametrize("maximum", (0, -1, True))
def test_risk_settings_rejects_invalid_maximum_open_positions(
    maximum: int,
) -> None:
    """Require a positive integer portfolio capacity."""
    with pytest.raises(ValueError, match="Maximum open positions"):
        RiskSettings(max_open_positions=maximum)


@pytest.mark.parametrize(
    "invalid_value",
    (
        Decimal("0"),
        Decimal("-0.001"),
        Decimal("1"),
        Decimal("1.001"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ),
)
def test_risk_settings_rejects_invalid_ema_cross_exit_ratios(
    invalid_value: Decimal,
) -> None:
    """Reject out-of-range and non-finite EMA cross exit ratios cleanly."""
    with pytest.raises(ValueError, match="ema_cross_stop_loss_pct"):
        RiskSettings(ema_cross_stop_loss_pct=invalid_value)

    with pytest.raises(ValueError, match="ema_cross_take_profit_pct"):
        RiskSettings(ema_cross_take_profit_pct=invalid_value)


@pytest.mark.parametrize(
    ("stop_loss_pct", "take_profit_pct"),
    (
        (Decimal("0.02"), Decimal("0.02")),
        (Decimal("0.03"), Decimal("0.02")),
    ),
)
def test_risk_settings_requires_ema_cross_take_profit_above_stop_loss(
    stop_loss_pct: Decimal,
    take_profit_pct: Decimal,
) -> None:
    """Require the EMA cross reward target to exceed its risk distance."""
    with pytest.raises(ValueError, match="EMA cross take-profit"):
        RiskSettings(
            ema_cross_stop_loss_pct=stop_loss_pct,
            ema_cross_take_profit_pct=take_profit_pct,
        )


# =============================================================================
# Environment and Settings Manager Tests
# =============================================================================
def test_environment_provider_rejects_an_empty_path() -> None:
    """Verify a dotenv path cannot be blank."""
    with pytest.raises(ValueError, match="must not be empty"):
        EnvironmentProvider(env_path="   ")


def test_default_base_configuration_remains_safe_without_soak_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep an ordinary base dotenv file PAPER-only without bootstrap selection."""
    _clear_environment(monkeypatch)
    base_path = tmp_path / ".env"
    _write_environment_file(
        base_path,
        "\n".join(
            (
                "TRADE_MODE=paper",
                "BINANCE_MARKET_TYPE=futures",
                "BINANCE_TESTNET=false",
                "EXECUTION_POLICY=single_symbol",
                "AUTONOMOUS_LIVE_ENTRY_ENABLED=false",
            )
        ),
    )

    settings = SettingsManager(
        environment_provider=EnvironmentProvider(env_path=str(base_path))
    ).load()

    assert settings.app.trade_mode is TradeMode.PAPER
    assert settings.exchange.environment is ExchangeEnvironment.MAINNET
    assert settings.app.effective_execution_policy is ExecutionPolicy.SINGLE_SYMBOL
    assert not settings.app.autonomous_live_entry_enabled


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    (
        ("true", True),
        ("YES", True),
        ("1", True),
        ("false", False),
        ("Off", False),
        ("0", False),
    ),
)
def test_environment_provider_parses_strict_booleans(
    raw_value: str,
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify supported boolean spellings are normalized."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("BINANCE_TESTNET", raw_value)

    assert provider.get_binance_testnet() is expected


def test_environment_provider_rejects_an_unknown_boolean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify ambiguous boolean values fail configuration loading."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("BINANCE_TESTNET", "sometimes")

    with pytest.raises(ValueError, match="BINANCE_TESTNET"):
        provider.get_binance_testnet()


def test_environment_provider_loads_autonomous_execution_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify autonomous execution defaults off and parses strict booleans."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )

    assert not provider.get_autonomous_execution_enabled()

    monkeypatch.setenv("AUTONOMOUS_EXECUTION_ENABLED", "true")

    assert provider.get_autonomous_execution_enabled()


def test_environment_provider_rejects_invalid_autonomous_execution_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify ambiguous autonomous execution values fail closed."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("AUTONOMOUS_EXECUTION_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="AUTONOMOUS_EXECUTION_ENABLED"):
        provider.get_autonomous_execution_enabled()


def test_environment_provider_loads_autonomous_live_entry_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Require a separate, strict opt-in for future autonomous LIVE entry."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )

    assert not provider.get_autonomous_live_entry_enabled()

    monkeypatch.setenv("AUTONOMOUS_LIVE_ENTRY_ENABLED", "true")

    assert provider.get_autonomous_live_entry_enabled()


def test_autonomous_live_entry_authorization_is_testnet_only_and_immutable() -> None:
    """Keep future autonomous entry separate from general LIVE state."""
    authorization = AutonomousLiveEntryAuthorization(
        environment=ExchangeEnvironment.TESTNET,
        explicit_opt_in=True,
    )

    assert authorization.new_live_entry_allowed
    with pytest.raises(FrozenInstanceError):
        setattr(authorization, "explicit_opt_in", False)
    with pytest.raises(ValueError, match="TESTNET"):
        AutonomousLiveEntryAuthorization(
            environment=ExchangeEnvironment.MAINNET,
            explicit_opt_in=True,
        )
    with pytest.raises(ValueError, match="opt-in"):
        AutonomousLiveEntryAuthorization(
            environment=ExchangeEnvironment.TESTNET,
            explicit_opt_in=False,
        )


def test_recovered_management_authorization_cannot_be_entry_authorization() -> None:
    """Keep exact recovered-position management separate from new entry consent."""
    management = LiveRecoveredPositionManagementAuthorization(
        contexts=(
            LiveRuntimePositionContext(
                symbol="BTCUSDT",
                interval=Interval.M1,
                strategy_type=StrategyType.EMA_CROSS,
            ),
        ),
        runtime_management_allowed=True,
    )

    assert not isinstance(management, AutonomousLiveEntryAuthorization)
    assert not management.new_live_entry_allowed


def test_settings_manager_allows_paper_autonomous_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify the safe PAPER configuration enables autonomous execution."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("TRADE_MODE", "paper")
    monkeypatch.setenv("AUTONOMOUS_EXECUTION_ENABLED", "true")

    settings = SettingsManager(environment_provider=provider).load()

    assert settings.app.trade_mode is TradeMode.PAPER
    assert settings.app.autonomous_execution_enabled


def test_settings_manager_loads_explicit_testnet_live_entry_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load the separate LIVE capability request without changing policy."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("TRADE_MODE", "live")
    monkeypatch.setenv("BINANCE_API_KEY", "configured-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "configured-secret")
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    monkeypatch.setenv("BINANCE_MARKET_TYPE", "futures")
    monkeypatch.setenv("AUTONOMOUS_LIVE_ENTRY_ENABLED", "true")

    settings = SettingsManager(environment_provider=provider).load()

    assert settings.app.trade_mode is TradeMode.LIVE
    assert settings.app.autonomous_live_entry_enabled
    assert settings.exchange.environment is ExchangeEnvironment.TESTNET
    assert settings.app.effective_execution_policy is ExecutionPolicy.SINGLE_SYMBOL


def test_settings_manager_loads_explicit_human_confirmation_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Select PAPER human confirmation without changing the legacy default."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("EXECUTION_POLICY", "human_confirmed_paper")

    settings = SettingsManager(environment_provider=provider).load()

    assert settings.app.execution_policy is ExecutionPolicy.HUMAN_CONFIRMED_PAPER
    assert (
        settings.app.effective_execution_policy is ExecutionPolicy.HUMAN_CONFIRMED_PAPER
    )


def test_settings_manager_loads_testnet_autonomous_live_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Accept only the explicit TESTNET autonomous LIVE intent workflow."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("TRADE_MODE", "live")
    monkeypatch.setenv("BINANCE_API_KEY", "configured-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "configured-secret")
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    monkeypatch.setenv("BINANCE_MARKET_TYPE", "futures")
    monkeypatch.setenv("AUTONOMOUS_LIVE_ENTRY_ENABLED", "true")
    monkeypatch.setenv("EXECUTION_POLICY", "autonomous_live")

    settings = SettingsManager(environment_provider=provider).load()

    assert settings.app.effective_execution_policy is ExecutionPolicy.AUTONOMOUS_LIVE


def test_settings_validation_rejects_conflicting_legacy_and_human_policy() -> None:
    """Fail closed when the legacy autonomous flag conflicts with confirmation."""
    with pytest.raises(ValueError, match="conflicts"):
        AppSettings(
            execution_policy=ExecutionPolicy.HUMAN_CONFIRMED_PAPER,
            autonomous_execution_enabled=True,
        )


def test_settings_manager_loads_ema_scalping_risk_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load exact strategy exit ratios from the shared environment profile."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("EMA_SCALPING_STOP_LOSS_PCT", "0.004")
    monkeypatch.setenv("EMA_SCALPING_TAKE_PROFIT_PCT", "0.009")

    settings = SettingsManager(environment_provider=provider).load_risk_settings()

    assert settings.ema_scalping_stop_loss_pct == Decimal("0.004")
    assert settings.ema_scalping_take_profit_pct == Decimal("0.009")


def test_settings_manager_loads_ema_cross_risk_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load exact EMA cross exit ratios from the environment."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("EMA_CROSS_STOP_LOSS_PCT", "0.001")
    monkeypatch.setenv("EMA_CROSS_TAKE_PROFIT_PCT", "0.0015")

    settings = SettingsManager(environment_provider=provider).load_risk_settings()

    assert settings.ema_cross_stop_loss_pct == Decimal("0.001")
    assert settings.ema_cross_take_profit_pct == Decimal("0.0015")


def test_settings_manager_loads_category_risk_profiles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load category-based risk overrides for scalping, trend, and swing."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("SCALPING_STOP_LOSS_PCT", "0.003")
    monkeypatch.setenv("SCALPING_TAKE_PROFIT_PCT", "0.008")
    monkeypatch.setenv("TREND_STOP_LOSS_PCT", "0.012")
    monkeypatch.setenv("TREND_TAKE_PROFIT_PCT", "0.025")
    monkeypatch.setenv("SWING_STOP_LOSS_PCT", "0.03")
    monkeypatch.setenv("SWING_TAKE_PROFIT_PCT", "0.06")
    monkeypatch.setenv("STOP_LOSS_PCT", "0.015")
    monkeypatch.setenv("TAKE_PROFIT_PCT", "0.035")

    settings = SettingsManager(environment_provider=provider).load_risk_settings()

    assert settings.scalping_stop_loss_pct == Decimal("0.003")
    assert settings.scalping_take_profit_pct == Decimal("0.008")
    assert settings.trend_stop_loss_pct == Decimal("0.012")
    assert settings.trend_take_profit_pct == Decimal("0.025")
    assert settings.swing_stop_loss_pct == Decimal("0.03")
    assert settings.swing_take_profit_pct == Decimal("0.06")
    assert settings.stop_loss_pct == Decimal("0.015")
    assert settings.take_profit_pct == Decimal("0.035")


def test_settings_manager_preserves_ema_cross_compatibility_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve the v1.0.3 EMA cross exit behavior when env values are absent."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )

    settings = SettingsManager(environment_provider=provider).load_risk_settings()

    assert settings.ema_cross_stop_loss_pct == Decimal("0.02")
    assert settings.ema_cross_take_profit_pct == Decimal("0.04")


@pytest.mark.parametrize(
    ("profile", "testnet", "expected_api_key"),
    (
        (EnvironmentProfile.TESTNET, True, "testnet-key"),
        (EnvironmentProfile.MAINNET, False, "mainnet-key"),
    ),
)
def test_environment_provider_loads_isolated_credential_profile(
    profile: EnvironmentProfile,
    testnet: bool,
    expected_api_key: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify the selected profile overrides base exchange credentials."""
    _clear_environment(monkeypatch)
    base_path = tmp_path / ".env"
    profile_path = tmp_path / f".env.{profile.value}"
    _write_environment_file(
        base_path,
        "\n".join(
            (
                f"BOTRAGRAM_PROFILE={profile.value}",
                "BINANCE_API_KEY=base-key",
                "BINANCE_API_SECRET=base-secret",
            )
        ),
    )
    _write_environment_file(
        profile_path,
        "\n".join(
            (
                f"BINANCE_API_KEY={expected_api_key}",
                "BINANCE_API_SECRET=profile-secret",
                f"BINANCE_TESTNET={str(testnet).lower()}",
            )
        ),
    )

    provider = EnvironmentProvider(env_path=str(base_path), override=True)

    assert provider.profile is profile
    assert provider.profile_path == str(profile_path)
    assert provider.get_binance_api_key() == expected_api_key
    assert provider.get_binance_api_secret() == "profile-secret"
    assert provider.get_binance_testnet() is testnet


def test_explicit_soak_environment_file_builds_testnet_autonomous_authorization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Resolve the dedicated soak base and TESTNET credentials without startup."""
    _clear_environment(monkeypatch)
    soak_path = tmp_path / ".env.autonomous_testnet_soak"
    _write_environment_file(
        soak_path,
        "\n".join(
            (
                "BOTRAGRAM_PROFILE=testnet",
                "TRADE_MODE=live",
                "BINANCE_MARKET_TYPE=futures",
                "EXECUTION_POLICY=autonomous_live",
                "AUTONOMOUS_LIVE_ENTRY_ENABLED=true",
                "MARKET_INTERVAL=1m",
                "DISCOVERY_UNIVERSE_LIMIT=100",
                "DISCOVERY_BATCH_SIZE=20",
                "DISCOVERY_CADENCE_SECONDS=10",
                "MAX_POSITION_SIZE_USDT=10",
                "MAX_OPEN_POSITIONS=1",
            )
        ),
    )
    _write_environment_file(
        tmp_path / ".env.autonomous_testnet_soak.testnet",
        "\n".join(
            (
                "BINANCE_API_KEY=testnet-key",
                "BINANCE_API_SECRET=testnet-secret",
                "BINANCE_TESTNET=true",
            )
        ),
    )
    monkeypatch.setenv("BOTRAGRAM_ENV_FILE", str(soak_path))

    settings = SettingsManager().load()
    provider = DependencyProvider(
        database_path=tmp_path / "botragram.db",
        settings=settings,
    )

    assert settings.app.trade_mode is TradeMode.LIVE
    assert settings.exchange.market_type is MarketType.FUTURES
    assert settings.exchange.environment is ExchangeEnvironment.TESTNET
    assert settings.app.effective_execution_policy is ExecutionPolicy.AUTONOMOUS_LIVE
    assert settings.app.autonomous_live_entry_enabled
    assert settings.risk.max_position_size_usdt == Decimal("10")
    assert settings.risk.max_open_positions == 1
    assert settings.market.interval is Interval.M1
    assert settings.market.discovery_universe_limit == 100
    assert settings.market.discovery_batch_size == 20
    assert settings.market.discovery_cadence_seconds == 10
    assert provider.autonomous_live_entry_authorization is not None
    asyncio.run(provider.close())


def test_explicit_soak_environment_file_fails_without_testnet_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Never fall back to default or MAINNET credentials for a soak selection."""
    _clear_environment(monkeypatch)
    soak_path = tmp_path / ".env.autonomous_testnet_soak"
    _write_environment_file(
        soak_path,
        "\n".join(
            (
                "BOTRAGRAM_PROFILE=testnet",
                "TRADE_MODE=live",
                "BINANCE_MARKET_TYPE=futures",
                "EXECUTION_POLICY=autonomous_live",
                "AUTONOMOUS_LIVE_ENTRY_ENABLED=true",
            )
        ),
    )
    _write_environment_file(
        tmp_path / ".env.autonomous_testnet_soak.testnet",
        "\n".join(
            (
                "BINANCE_API_KEY=",
                "BINANCE_API_SECRET=",
                "BINANCE_TESTNET=true",
            )
        ),
    )
    monkeypatch.setenv("BOTRAGRAM_ENV_FILE", str(soak_path))

    with pytest.raises(ValueError, match="Live trading requires"):
        SettingsManager().load()


def test_explicit_missing_soak_environment_file_fails_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a missing requested base file before default dotenv can load."""
    _clear_environment(monkeypatch)
    monkeypatch.setenv(
        "BOTRAGRAM_ENV_FILE",
        str(tmp_path / ".env.autonomous_testnet_soak"),
    )

    with pytest.raises(FileNotFoundError, match="Explicit environment file"):
        EnvironmentProvider()


def test_dotenv_overrides_stale_terminal_configuration_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Prevent inherited terminal values from changing the selected profile."""
    _clear_environment(monkeypatch)
    monkeypatch.setenv("BOTRAGRAM_PROFILE", "testnet")
    monkeypatch.setenv("BINANCE_MARKET_TYPE", "spot")
    base_path = tmp_path / ".env"
    _write_environment_file(
        base_path,
        "\n".join(
            (
                "BOTRAGRAM_PROFILE=mainnet",
                "BINANCE_MARKET_TYPE=futures",
            )
        ),
    )
    _write_environment_file(
        tmp_path / ".env.mainnet",
        "\n".join(
            (
                "BINANCE_API_KEY=mainnet-key",
                "BINANCE_API_SECRET=mainnet-secret",
                "BINANCE_TESTNET=false",
            )
        ),
    )

    provider = EnvironmentProvider(env_path=str(base_path))

    assert provider.profile is EnvironmentProfile.MAINNET
    assert provider.get_binance_market_type() == "FUTURES"
    assert not provider.get_binance_testnet()


def test_environment_provider_rejects_unknown_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify an unknown credential profile cannot select a dotenv file."""
    _clear_environment(monkeypatch)
    base_path = tmp_path / ".env"
    _write_environment_file(base_path, "BOTRAGRAM_PROFILE=staging")

    with pytest.raises(ValueError, match="BOTRAGRAM_PROFILE"):
        EnvironmentProvider(env_path=str(base_path), override=True)


def test_environment_provider_requires_selected_profile_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify an explicitly selected profile cannot fall back to base keys."""
    _clear_environment(monkeypatch)
    base_path = tmp_path / ".env"
    _write_environment_file(base_path, "BOTRAGRAM_PROFILE=testnet")

    with pytest.raises(FileNotFoundError, match="does not exist"):
        EnvironmentProvider(env_path=str(base_path), override=True)


def test_environment_provider_rejects_profile_network_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify a mainnet profile cannot target a testnet endpoint."""
    _clear_environment(monkeypatch)
    base_path = tmp_path / ".env"
    _write_environment_file(base_path, "BOTRAGRAM_PROFILE=mainnet")
    _write_environment_file(
        tmp_path / ".env.mainnet",
        "\n".join(
            (
                "BINANCE_API_KEY=mainnet-key",
                "BINANCE_API_SECRET=mainnet-secret",
                "BINANCE_TESTNET=true",
            )
        ),
    )

    with pytest.raises(ValueError, match="requires BINANCE_TESTNET=false"):
        EnvironmentProvider(env_path=str(base_path), override=True)


def test_settings_manager_builds_complete_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify environment values form one validated settings aggregate."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("ACTIVE_EXCHANGE", "binance")
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    monkeypatch.setenv("BINANCE_MARKET_TYPE", "futures")
    monkeypatch.setenv("LOG_LEVEL", "warning")
    monkeypatch.setenv("TELEGRAM_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("TRADE_MODE", "paper")

    settings = SettingsManager(environment_provider=provider).load()

    assert settings.exchange.exchange is ExchangeType.BINANCE
    assert settings.exchange.market_type is MarketType.FUTURES
    assert settings.exchange.is_live
    assert settings.logging.level is LogLevel.WARNING
    assert settings.app.trade_mode is TradeMode.PAPER
    assert settings.telegram.enabled
    assert settings.telegram.allowed_chat_ids == [12345]


def test_settings_manager_rejects_unknown_exchange(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify invalid exchange values never fall back silently."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("ACTIVE_EXCHANGE", "unknown")
    settings_manager = SettingsManager(environment_provider=provider)

    with pytest.raises(ValueError, match="ACTIVE_EXCHANGE"):
        settings_manager.load()


def test_settings_manager_rejects_unknown_binance_market_type(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify an unknown Binance product cannot silently select Spot."""
    provider = _create_environment_provider(
        monkeypatch=monkeypatch,
        temporary_path=tmp_path,
    )
    monkeypatch.setenv("BINANCE_MARKET_TYPE", "margin")
    settings_manager = SettingsManager(environment_provider=provider)

    with pytest.raises(ValueError, match="BINANCE_MARKET_TYPE"):
        settings_manager.load()


def test_settings_validation_rejects_partial_credentials() -> None:
    """Verify exchange key and secret must be configured together."""
    settings = Settings(
        exchange=ExchangeSettings(
            exchange=ExchangeType.BINANCE,
            api_key="key-only",
        ),
    )

    with pytest.raises(ValueError, match="configured together"):
        SettingsManager.validate(settings=settings)


def test_settings_validation_rejects_live_mode_without_credentials() -> None:
    """Verify live trading cannot start without exchange credentials."""
    settings = Settings(
        app=AppSettings(trade_mode=TradeMode.LIVE),
        exchange=ExchangeSettings(exchange=ExchangeType.BINANCE),
    )

    with pytest.raises(ValueError, match="Live trading requires"):
        SettingsManager.validate(settings=settings)


def test_settings_validation_rejects_autonomous_live_mode() -> None:
    """Verify autonomous execution cannot be routed to live trading."""
    settings = Settings(
        app=AppSettings(
            trade_mode=TradeMode.LIVE,
            autonomous_execution_enabled=True,
        ),
        exchange=ExchangeSettings(
            exchange=ExchangeType.BINANCE,
            api_key="configured-key",
            api_secret="configured-secret",
        ),
    )

    with pytest.raises(ValueError, match="only in paper mode"):
        SettingsManager.validate(settings=settings)


def test_settings_validation_requires_live_testnet_for_autonomous_live_entry() -> None:
    """Reject PAPER and MAINNET before provider composition can grant capability."""
    paper_settings = Settings(
        app=AppSettings(autonomous_live_entry_enabled=True),
        exchange=ExchangeSettings(exchange=ExchangeType.BINANCE),
    )
    mainnet_settings = Settings(
        app=AppSettings(
            trade_mode=TradeMode.LIVE,
            autonomous_live_entry_enabled=True,
        ),
        exchange=ExchangeSettings(
            exchange=ExchangeType.BINANCE,
            api_key="configured-key",
            api_secret="configured-secret",
            testnet=False,
        ),
    )

    with pytest.raises(ValueError, match="requires LIVE mode"):
        SettingsManager.validate(settings=paper_settings)
    with pytest.raises(ValueError, match="requires TESTNET"):
        SettingsManager.validate(settings=mainnet_settings)


@pytest.mark.parametrize(
    ("app_settings", "exchange_settings", "message"),
    (
        (
            AppSettings(execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE),
            ExchangeSettings(exchange=ExchangeType.BINANCE),
            "requires LIVE mode",
        ),
        (
            AppSettings(
                trade_mode=TradeMode.LIVE,
                execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
            ),
            ExchangeSettings(
                exchange=ExchangeType.BINANCE,
                market_type=MarketType.FUTURES,
                api_key="configured-key",
                api_secret="configured-secret",
            ),
            "requires explicit opt-in",
        ),
        (
            AppSettings(
                trade_mode=TradeMode.LIVE,
                execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
                autonomous_live_entry_enabled=True,
            ),
            ExchangeSettings(
                exchange=ExchangeType.BINANCE,
                market_type=MarketType.FUTURES,
                api_key="configured-key",
                api_secret="configured-secret",
                testnet=False,
            ),
            "requires TESTNET",
        ),
        (
            AppSettings(
                trade_mode=TradeMode.LIVE,
                execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
                autonomous_live_entry_enabled=True,
            ),
            ExchangeSettings(
                exchange=ExchangeType.BINANCE,
                api_key="configured-key",
                api_secret="configured-secret",
            ),
            "requires FUTURES",
        ),
    ),
)
def test_settings_validation_rejects_invalid_autonomous_live_workflow(
    app_settings: AppSettings,
    exchange_settings: ExchangeSettings,
    message: str,
) -> None:
    """Reject every incomplete autonomous LIVE workflow combination."""
    with pytest.raises(ValueError, match=message):
        SettingsManager.validate(
            settings=Settings(
                app=app_settings,
                exchange=exchange_settings,
            )
        )


def test_dependency_provider_builds_testnet_entry_authorization(
    tmp_path: Path,
) -> None:
    """Construct the capability only in composition, without execution wiring."""
    provider = DependencyProvider(
        database_path=tmp_path / "botragram.db",
        settings=Settings(
            app=AppSettings(
                trade_mode=TradeMode.LIVE,
                autonomous_live_entry_enabled=True,
            ),
            exchange=ExchangeSettings(
                exchange=ExchangeType.BINANCE,
                api_key="configured-key",
                api_secret="configured-secret",
                testnet=True,
            ),
        ),
    )

    authorization = provider.autonomous_live_entry_authorization

    assert authorization is not None
    assert authorization.environment is ExchangeEnvironment.TESTNET
    assert authorization.new_live_entry_allowed
    asyncio.run(provider.close())
    assert provider.autonomous_live_entry_authorization is None


def test_dependency_provider_builds_testnet_autonomous_live_intent_boundary(
    tmp_path: Path,
) -> None:
    """Compose the pure intent boundary without a LIVE execution route."""
    provider = DependencyProvider(
        database_path=tmp_path / "botragram.db",
        settings=Settings(
            app=AppSettings(
                trade_mode=TradeMode.LIVE,
                execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
                autonomous_live_entry_enabled=True,
            ),
            exchange=ExchangeSettings(
                exchange=ExchangeType.BINANCE,
                api_key="configured-key",
                api_secret="configured-secret",
                testnet=True,
            ),
        ),
    )

    assert provider.autonomous_live_entry_authorization is not None
    assert provider.autonomous_live_entry_intent_service is not None
    asyncio.run(provider.close())
    assert provider.autonomous_live_entry_intent_service is None


def test_dependency_provider_rejects_mainnet_autonomous_live_entry(
    tmp_path: Path,
) -> None:
    """Prevent direct provider construction from bypassing settings validation."""
    with pytest.raises(ValueError, match="requires TESTNET"):
        DependencyProvider(
            database_path=tmp_path / "botragram.db",
            settings=Settings(
                app=AppSettings(
                    trade_mode=TradeMode.LIVE,
                    autonomous_live_entry_enabled=True,
                ),
                exchange=ExchangeSettings(
                    exchange=ExchangeType.BINANCE,
                    api_key="configured-key",
                    api_secret="configured-secret",
                    testnet=False,
                ),
            ),
        )


def test_dependency_provider_rejects_mainnet_autonomous_live_workflow(
    tmp_path: Path,
) -> None:
    """Reject MAINNET before the autonomous LIVE intent boundary can exist."""
    with pytest.raises(ValueError, match="requires TESTNET"):
        DependencyProvider(
            database_path=tmp_path / "botragram.db",
            settings=Settings(
                app=AppSettings(
                    trade_mode=TradeMode.LIVE,
                    execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
                    autonomous_live_entry_enabled=True,
                ),
                exchange=ExchangeSettings(
                    exchange=ExchangeType.BINANCE,
                    api_key="configured-key",
                    api_secret="configured-secret",
                    testnet=False,
                ),
            ),
        )


def test_safe_default_has_no_autonomous_live_entry_authorization(
    tmp_path: Path,
) -> None:
    """Keep default PAPER composition free of future LIVE entry permission."""
    provider = DependencyProvider(
        database_path=tmp_path / "botragram.db",
        settings=Settings(exchange=ExchangeSettings(exchange=ExchangeType.BINANCE)),
    )

    assert provider.autonomous_live_entry_authorization is None


# =============================================================================
# Utility Tests
# =============================================================================
def test_decimal_utilities_preserve_trading_precision() -> None:
    """Verify Decimal conversion and exchange increment rounding."""
    assert to_decimal(1.25) == Decimal("1.25")
    assert to_decimal(Decimal("2.5")) == Decimal("2.5")
    assert round_step_size(
        Decimal("1.239"),
        Decimal("0.01"),
    ) == Decimal("1.23")
    assert round_price_precision(
        Decimal("45123.456"),
        Decimal("0.1"),
    ) == Decimal("45123.5")


def test_datetime_utilities_use_utc() -> None:
    """Verify timestamp conversion and formatting remain UTC-aware."""
    timestamp_ms = 1_700_000_000_000
    converted = timestamp_ms_to_datetime(timestamp_ms)

    assert converted.tzinfo is timezone.utc
    assert int(converted.timestamp() * 1_000) == timestamp_ms
    assert current_utc_timestamp_ms() > timestamp_ms
    assert (
        format_utc_datetime(
            datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        )
        == "2026-01-02 03:04:00 UTC"
    )


def test_formatting_utilities_return_stable_display_values() -> None:
    """Verify currency, percentage, and price formatting."""
    assert format_currency(Decimal("100.5"), "USDT") == "100.50 USDT"
    assert format_percentage(Decimal("0.052")) == "+5.20%"
    assert format_percentage(Decimal("-0.01")) == "-1.00%"
    assert format_price(Decimal("0.123")) == "0.123"
    assert format_price(Decimal("0.002246")) == "0.002246"
    assert format_price(Decimal("100.50")) == "100.50"
    assert format_price(Decimal("100")) == "100.00"
    assert format_price(Decimal("671.770")) == "671.77"
    assert format_price(Decimal("0.123"), symbol="USDT") == "0.123 USDT"
    assert format_price(Decimal("27"), min_decimals=0) == "27"


def test_validation_utilities_accept_and_reject_domain_values() -> None:
    """Verify common validation helpers enforce their contracts."""
    validate_positive_decimal(Decimal("0.01"), "quantity")
    validate_symbol("BTCUSDT")
    zero_quantity = Decimal("0")

    with pytest.raises(ValueError, match="quantity"):
        validate_positive_decimal(zero_quantity, "quantity")

    for invalid_symbol in ("", "   ", "BTC/USDT"):
        with pytest.raises(ValueError, match="Invalid trading symbol"):
            validate_symbol(invalid_symbol)
