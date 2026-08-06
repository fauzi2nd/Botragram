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
from botragram.enums import Environment, ExchangeType, LogLevel, TradeMode
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
    "AI_MODEL",
    "AI_PROVIDER",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_TESTNET",
    "BOTRAGRAM_EXCHANGE_API_KEY",
    "BOTRAGRAM_EXCHANGE_API_SECRET",
    "BOTRAGRAM_LOG_LEVEL",
    "BOTRAGRAM_TELEGRAM_TOKEN",
    "BOTRAGRAM_TRADE_MODE",
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
    for key in _ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)

    return EnvironmentProvider(
        env_path=str(temporary_path / "missing.env"),
    )


# =============================================================================
# Configuration Tests
# =============================================================================
def test_configuration_defaults_are_safe_and_immutable() -> None:
    """Verify default settings favor paper trading and testnet."""
    settings = Settings()

    assert settings.app.trade_mode is TradeMode.PAPER
    assert settings.exchange.exchange is ExchangeType.BINANCE
    assert settings.exchange.testnet
    assert not settings.exchange.is_live
    assert settings.market.symbol == "BTCUSDT"

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
    monkeypatch.setenv("LOG_LEVEL", "warning")
    monkeypatch.setenv("TELEGRAM_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("TRADE_MODE", "paper")

    settings = SettingsManager(environment_provider=provider).load()

    assert settings.exchange.exchange is ExchangeType.BINANCE
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
