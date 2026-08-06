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
# Local Imports
# =============================================================================
from botragram.app import Application, ApplicationLifecycle, DependencyProvider
from botragram.config import Settings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.enums import ExchangeType
from botragram.exchanges.base import BaseExchangeClient, BaseStreamClient
from botragram.services import TradingService


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
            assert provider.trading_service.market_service is provider.market_service
            assert provider.trading_service.order_service is provider.order_service
            assert await provider.candle_repository.count() == 0

        application = Application(
            settings=provider.settings,
            lifecycle=lifecycle,
            runner=runner,
        )
        await application.run()

        assert runner_executed
        assert not provider.is_initialized
