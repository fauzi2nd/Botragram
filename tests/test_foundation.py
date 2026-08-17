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
from botragram.app import SettingsManager
from botragram.app.environment_provider import EnvironmentProvider
from botragram.config import Settings
from botragram.config.app_settings import AppSettings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.config.market_settings import MarketSettings
from botragram.config.risk_settings import RiskSettings
from botragram.enums import (
    Environment,
    EnvironmentProfile,
    ExchangeType,
    ExecutionPolicy,
    LogLevel,
    MarketType,
    TradeMode,
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
from botragram.utils.formatter import format_currency, format_percentage
from botragram.utils.validator import validate_positive_decimal, validate_symbol

# =============================================================================
# Constants
# =============================================================================
_ENVIRONMENT_KEYS = (
    "ACTIVE_EXCHANGE",
    "AUTONOMOUS_EXECUTION_ENABLED",
    "AI_MODEL",
    "AI_PROVIDER",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_MARKET_TYPE",
    "BINANCE_TESTNET",
    "BOTRAGRAM_PROFILE",
    "BOTRAGRAM_EXCHANGE_API_KEY",
    "BOTRAGRAM_EXCHANGE_API_SECRET",
    "BOTRAGRAM_LOG_LEVEL",
    "BOTRAGRAM_TELEGRAM_TOKEN",
    "BOTRAGRAM_TRADE_MODE",
    "EMA_SCALPING_STOP_LOSS_PCT",
    "EMA_SCALPING_TAKE_PROFIT_PCT",
    "EXECUTION_POLICY",
    "GEMINI_API_KEY",
    "LOG_LEVEL",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
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
    assert settings.exchange.exchange is ExchangeType.BINANCE
    assert settings.exchange.testnet
    assert not settings.exchange.is_live
    assert settings.market.symbol == "BTCUSDT"
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


@pytest.mark.parametrize("maximum", (0, -1, True))
def test_risk_settings_rejects_invalid_maximum_open_positions(
    maximum: int,
) -> None:
    """Require a positive integer portfolio capacity."""
    with pytest.raises(ValueError, match="Maximum open positions"):
        RiskSettings(max_open_positions=maximum)


# =============================================================================
# Environment and Settings Manager Tests
# =============================================================================
def test_environment_provider_rejects_an_empty_path() -> None:
    """Verify a dotenv path cannot be blank."""
    with pytest.raises(ValueError, match="must not be empty"):
        EnvironmentProvider(env_path="   ")


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
    """Verify currency and percentage formatting."""
    assert format_currency(Decimal("100.5"), "USDT") == "100.50 USDT"
    assert format_percentage(Decimal("0.052")) == "+5.20%"
    assert format_percentage(Decimal("-0.01")) == "-1.00%"


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
