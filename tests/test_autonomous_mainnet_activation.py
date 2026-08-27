"""
Botragram

Description:
    Guarded autonomous MAINNET activation-boundary regression tests.

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
from botragram.config.telegram_settings import TelegramSettings
from botragram.enums import (
    ExchangeEnvironment,
    ExchangeType,
    ExecutionPolicy,
    MarketType,
    TradeMode,
)
from botragram.models import AutonomousLiveEntryAuthorization
from botragram.services import AutonomousLiveRecoveryObservabilityService
from botragram.storage.memory import MemorySubmissionAttemptRepository
from botragram.telegram.messages import get_autonomous_live_recovery_message


# =============================================================================
# Test Helpers
# =============================================================================
def _mainnet_settings(*, mainnet_opt_in: bool) -> Settings:
    """Build an isolated autonomous MAINNET configuration."""
    return Settings(
        app=AppSettings(
            trade_mode=TradeMode.LIVE,
            execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
            autonomous_live_entry_enabled=True,
            autonomous_mainnet_entry_enabled=mainnet_opt_in,
        ),
        exchange=ExchangeSettings(
            exchange=ExchangeType.BINANCE,
            market_type=MarketType.FUTURES,
            api_key="configured-key",
            api_secret="configured-secret",
            testnet=False,
        ),
        telegram=TelegramSettings(enabled=False),
    )


# =============================================================================
# Activation Boundary Tests
# =============================================================================
def test_mainnet_activation_requires_second_explicit_opt_in() -> None:
    """Keep the previous LIVE opt-in insufficient for MAINNET exposure."""
    with pytest.raises(ValueError, match="explicit MAINNET opt-in"):
        SettingsManager.validate(settings=_mainnet_settings(mainnet_opt_in=False))

    SettingsManager.validate(settings=_mainnet_settings(mainnet_opt_in=True))


def test_mainnet_opt_in_cannot_authorize_testnet_or_replace_base_opt_in() -> None:
    """Reject a misplaced MAINNET flag and an incomplete two-key handshake."""
    testnet_settings = Settings(
        app=AppSettings(
            trade_mode=TradeMode.LIVE,
            execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
            autonomous_live_entry_enabled=True,
            autonomous_mainnet_entry_enabled=True,
        ),
        exchange=ExchangeSettings(
            exchange=ExchangeType.BINANCE,
            market_type=MarketType.FUTURES,
            api_key="configured-key",
            api_secret="configured-secret",
            testnet=True,
        ),
    )
    missing_base = Settings(
        app=AppSettings(
            trade_mode=TradeMode.LIVE,
            execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
            autonomous_mainnet_entry_enabled=True,
        ),
        exchange=_mainnet_settings(mainnet_opt_in=True).exchange,
    )

    with pytest.raises(ValueError, match="requires MAINNET"):
        SettingsManager.validate(settings=testnet_settings)
    with pytest.raises(ValueError, match="requires explicit opt-in"):
        SettingsManager.validate(settings=missing_base)


def test_environment_provider_defaults_mainnet_activation_to_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Parse the additional opt-in strictly while preserving a safe default."""
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)
    monkeypatch.delenv("AUTONOMOUS_MAINNET_ENTRY_ENABLED", raising=False)
    provider = EnvironmentProvider(env_path=str(tmp_path / "missing.env"))

    assert not provider.get_autonomous_mainnet_entry_enabled()

    monkeypatch.setenv("AUTONOMOUS_MAINNET_ENTRY_ENABLED", "true")

    assert provider.get_autonomous_mainnet_entry_enabled()


def test_dependency_provider_composes_exact_mainnet_capability(
    tmp_path: Path,
) -> None:
    """Compose MAINNET only after both immutable opt-ins are present."""
    provider = DependencyProvider(
        database_path=tmp_path / "botragram-mainnet.db",
        settings=_mainnet_settings(mainnet_opt_in=True),
    )

    authorization = provider.autonomous_live_entry_authorization

    assert authorization is not None
    assert authorization.environment is ExchangeEnvironment.MAINNET
    assert authorization.explicit_opt_in
    assert authorization.mainnet_explicit_opt_in
    assert provider.autonomous_live_entry_intent_service is not None
    asyncio.run(provider.close())


def test_mainnet_capability_cannot_cross_network_boundary() -> None:
    """Make the second opt-in valid only for an exact MAINNET capability."""
    with pytest.raises(ValueError, match="TESTNET or explicit MAINNET opt-in"):
        AutonomousLiveEntryAuthorization(
            environment=ExchangeEnvironment.MAINNET,
            explicit_opt_in=True,
        )
    with pytest.raises(ValueError, match="requires MAINNET environment"):
        AutonomousLiveEntryAuthorization(
            environment=ExchangeEnvironment.TESTNET,
            explicit_opt_in=True,
            mainnet_explicit_opt_in=True,
        )


def test_mainnet_recovery_observability_reports_actual_network() -> None:
    """Avoid presenting a MAINNET capability to operators as TESTNET."""
    authorization = AutonomousLiveEntryAuthorization(
        environment=ExchangeEnvironment.MAINNET,
        explicit_opt_in=True,
        mainnet_explicit_opt_in=True,
    )
    snapshot = asyncio.run(
        AutonomousLiveRecoveryObservabilityService(
            submission_attempt_repository=MemorySubmissionAttemptRepository(),
            authorization=authorization,
        ).get_snapshot()
    )

    assert snapshot.autonomous_entry_environment is ExchangeEnvironment.MAINNET
    assert "ENABLED — MAINNET" in get_autonomous_live_recovery_message(
        snapshot=snapshot
    )
