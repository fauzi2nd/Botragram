"""
Botragram

Description:
    Process entry point and top-level application composition.

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
import logging
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import (
    Application,
    ApplicationLifecycle,
    DependencyProvider,
    SettingsManager,
    TradingRunner,
)
from botragram.config import Settings
from botragram.utils.logger import configure_logging, shutdown_logging

__all__ = [
    "main",
]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger("botragram.main")


# =============================================================================
# Runtime Functions
# =============================================================================
async def _run_trading(
    *,
    dependency_provider: DependencyProvider,
    settings: Settings,
) -> None:
    """Build and run trading orchestration after resources are initialized."""
    minimum_candles = dependency_provider.signal_engine.strategy.minimum_candles
    runner = TradingRunner(
        executor=dependency_provider.trading_service,
        symbol=settings.market.symbol,
        interval=settings.market.interval,
        trade_mode=settings.app.trade_mode,
        candle_limit=max(100, minimum_candles),
        cycle_interval_seconds=float(settings.market.interval.seconds),
        runtime_control=dependency_provider.runtime_control,
        runtime_observer=dependency_provider.runtime_reporter,
        maximum_consecutive_failures=3,
        failure_retry_delay_seconds=5.0,
    )
    await runner.run()


async def main() -> None:
    """Build and run the Botragram application."""
    settings = SettingsManager().load()
    configure_logging(settings=settings.logging)

    try:
        _LOGGER.info(
            "Application configuration loaded",
            extra={
                "environment": settings.app.environment.value,
                "exchange": settings.exchange.exchange.value,
                "testnet": settings.exchange.testnet,
                "trade_mode": settings.app.trade_mode.value,
            },
        )
        dependency_provider = DependencyProvider(
            database_path=settings.app.database_path,
            settings=settings,
        )
        lifecycle = ApplicationLifecycle(
            dependency_provider=dependency_provider,
        )
        application = Application(
            settings=settings,
            lifecycle=lifecycle,
            runner=lambda: _run_trading(
                dependency_provider=dependency_provider,
                settings=settings,
            ),
        )
        await application.run()
    finally:
        shutdown_logging()


if __name__ == "__main__":
    asyncio.run(main())
