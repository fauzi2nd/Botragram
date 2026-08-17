"""
Botragram

Description:
    Application dependency integration smoke tests.

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
from tempfile import TemporaryDirectory

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import (
    Application,
    ApplicationLifecycle,
    AutonomousPaperTradingCycleExecutor,
    DependencyProvider,
    SingleSymbolTradingCycleExecutor,
)
from botragram.config import Settings
from botragram.config.app_settings import AppSettings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.enums import ExchangeType
from botragram.exchanges.base import BaseExchangeClient, BaseStreamClient
from botragram.services import (
    AutonomousPaperExecutionService,
    ExecutionAuthorizationService,
    HealthService,
    PaperTradingService,
    RuntimeReporter,
    TradingService,
)
from botragram.telegram import TelegramBot


# =============================================================================
# Integration Tests
# =============================================================================
def test_application_builds_the_complete_trading_dependency_chain() -> None:
    """Verify application lifecycle exposes the complete dependency chain."""
    asyncio.run(_run_application_dependency_smoke_test())


async def _run_application_dependency_smoke_test() -> None:
    """Run an application lifecycle without making an exchange request."""
    with TemporaryDirectory() as temporary_directory:
        provider = DependencyProvider(
            database_path=Path(temporary_directory) / "botragram.db",
            settings=Settings(
                exchange=ExchangeSettings(exchange=ExchangeType.BINANCE),
            ),
        )
        lifecycle = ApplicationLifecycle(dependency_provider=provider)
        runner_executed = False

        async def runner() -> None:
            """Assert all dependencies are wired through the provider."""
            nonlocal runner_executed
            runner_executed = True

            assert isinstance(provider.exchange_client, BaseExchangeClient)
            assert isinstance(provider.stream_client, BaseStreamClient)
            assert isinstance(provider.trading_service, TradingService)
            assert isinstance(provider.paper_trading_service, PaperTradingService)
            assert isinstance(
                provider.autonomous_paper_execution_service,
                AutonomousPaperExecutionService,
            )
            assert isinstance(
                provider.execution_authorization_service,
                ExecutionAuthorizationService,
            )
            assert (
                provider.execution_authorization_service.authorization_publisher
                is provider.telegram_bot
            )
            assert isinstance(
                provider.trading_cycle_executor,
                SingleSymbolTradingCycleExecutor,
            )
            assert isinstance(provider.telegram_bot, TelegramBot)
            assert isinstance(provider.health_service, HealthService)
            assert isinstance(provider.runtime_reporter, RuntimeReporter)
            assert provider.trading_engine.portfolio_engine is provider.portfolio_engine
            assert provider.trading_service.market_service is provider.market_service
            assert provider.trading_service.order_service is provider.order_service
            assert (
                provider.trading_service.paper_trading_service
                is provider.paper_trading_service
            )
            assert (
                provider.paper_trading_service.notification_publisher
                is provider.telegram_bot
            )
            assert await provider.candle_repository.count() == 0

        application = Application(
            settings=provider.settings,
            lifecycle=lifecycle,
            runner=runner,
        )
        await application.run()

        assert runner_executed
        assert not provider.is_initialized

        with pytest.raises(RuntimeError, match="not been initialized"):
            _ = provider.autonomous_paper_execution_service

        with pytest.raises(RuntimeError, match="not been initialized"):
            _ = provider.execution_authorization_service


def test_provider_selects_paper_autonomous_executor() -> None:
    """Verify autonomous PAPER composition is built and reset by the provider."""
    asyncio.run(_run_autonomous_provider_test())


async def _run_autonomous_provider_test() -> None:
    """Initialize an autonomous PAPER provider without exchange requests."""
    with TemporaryDirectory() as temporary_directory:
        provider = DependencyProvider(
            database_path=Path(temporary_directory) / "botragram.db",
            settings=Settings(
                app=AppSettings(autonomous_execution_enabled=True),
                exchange=ExchangeSettings(exchange=ExchangeType.BINANCE),
            ),
        )

        async with provider:
            executor = provider.trading_cycle_executor

            assert isinstance(executor, AutonomousPaperTradingCycleExecutor)
            assert (
                executor.autonomous_execution_service
                is provider.autonomous_paper_execution_service
            )
            assert executor.quote_asset == provider.settings.market.quote_asset
            assert (
                executor.max_symbols == provider.settings.market.discovery_max_symbols
            )
            assert executor.top_n == provider.settings.market.discovery_top_n

        with pytest.raises(RuntimeError, match="not been initialized"):
            _ = provider.trading_cycle_executor
