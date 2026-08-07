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
    TerminalMonitor,
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
    terminal_monitor = TerminalMonitor(
        runtime_control=dependency_provider.runtime_control,
        paper_balance_provider=dependency_provider.paper_trading_service,
        live_balance_provider=dependency_provider.account_service,
        position_provider=dependency_provider.position_repository,
        pnl_engine=dependency_provider.pnl_engine,
        trade_mode=settings.app.trade_mode,
        quote_asset=settings.market.quote_asset,
    )
    monitor_task = asyncio.create_task(
        terminal_monitor.run(),
        name="botragram-terminal-monitor",
    )

    try:
        await dependency_provider.runtime_recovery_service.recover()
        minimum_candles = dependency_provider.signal_engine.strategy.minimum_candles
        runner = TradingRunner(
            executor=dependency_provider.trading_service,
            symbol=dependency_provider.runtime_control.symbol,
            interval=dependency_provider.runtime_control.interval,
            trade_mode=settings.app.trade_mode,
            candle_limit=max(100, minimum_candles),
            runtime_control=dependency_provider.runtime_control,
            runtime_observer=dependency_provider.runtime_reporter,
            maximum_consecutive_failures=3,
            failure_retry_delay_seconds=5.0,
        )
        await runner.run()
    finally:
        terminal_monitor.stop()
        await asyncio.gather(monitor_task, return_exceptions=True)


async def main() -> None:
    """Build and run the Botragram application."""
    settings = SettingsManager().load()
    configure_logging(settings=settings.logging)

    try:
        _LOGGER.info(
            "Configuration loaded: environment=%s exchange=%s market_type=%s "
            "testnet=%s trade_mode=%s symbol=%s strategy=%s",
            settings.app.environment.value,
            settings.exchange.exchange.value,
            settings.exchange.market_type.value,
            settings.exchange.testnet,
            settings.app.trade_mode.value,
            settings.market.symbol,
            settings.strategy.strategy_type.value,
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
