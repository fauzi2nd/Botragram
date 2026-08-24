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
import sys
from dataclasses import replace
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import (
    Application,
    ApplicationLifecycle,
    DependencyProvider,
    GlobalDiscoveryTelemetry,
    RuntimeRestartCoordinator,
    SettingsManager,
    TerminalMonitor,
    TradingRunner,
    run_until_restart,
)
from botragram.config import Settings
from botragram.enums import ExecutionPolicy, MarketType, TradeMode
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
    restart_coordinator: RuntimeRestartCoordinator,
) -> None:
    """Build and run trading orchestration after resources are initialized."""
    global_discovery_telemetry = (
        GlobalDiscoveryTelemetry(
            interval=settings.market.interval,
            max_symbols=settings.market.discovery_max_symbols,
            universe_limit=settings.market.discovery_universe_limit,
            batch_size=settings.market.discovery_batch_size,
            top_n=settings.market.discovery_top_n,
        )
        if settings.app.effective_execution_policy is ExecutionPolicy.AUTONOMOUS_LIVE
        else None
    )
    terminal_monitor = TerminalMonitor(
        runtime_control=dependency_provider.runtime_control,
        paper_balance_provider=dependency_provider.paper_trading_service,
        live_balance_provider=(
            dependency_provider.live_futures_user_data_service
            if settings.app.trade_mode is TradeMode.LIVE
            and settings.exchange.market_type is MarketType.FUTURES
            else dependency_provider.account_service
        ),
        position_provider=dependency_provider.position_repository,
        live_futures_user_data_service=(
            dependency_provider.live_futures_user_data_service
            if settings.app.trade_mode is TradeMode.LIVE
            and settings.exchange.market_type is MarketType.FUTURES
            else None
        ),
        live_balance_refresh_seconds=(
            0.0
            if settings.app.trade_mode is TradeMode.LIVE
            and settings.exchange.market_type is MarketType.FUTURES
            else 10.0
        ),
        pnl_engine=dependency_provider.pnl_engine,
        trade_mode=settings.app.trade_mode,
        quote_asset=settings.market.quote_asset,
        live_runtime_health_service=dependency_provider.live_runtime_health_service,
        live_trading_performance_service=(
            dependency_provider.live_trading_performance_service
        ),
        autonomous_live_recovery_observability_service=(
            dependency_provider.autonomous_live_recovery_observability_service
        ),
        global_discovery_telemetry_provider=global_discovery_telemetry,
        max_open_positions=settings.risk.max_open_positions,
    )
    monitor_task = asyncio.create_task(
        terminal_monitor.run(),
        name="botragram-terminal-monitor",
    )
    try:
        await dependency_provider.runtime_recovery_service.recover()
        runtime_contexts = dependency_provider.runtime_control.runtime_contexts
        strategy_types = (
            tuple(context.strategy_type for context in runtime_contexts)
            if runtime_contexts
            else (settings.strategy.strategy_type,)
        )
        minimum_candles = max(
            dependency_provider.signal_engine.get_minimum_candles(
                strategy_type=strategy_type,
            )
            for strategy_type in strategy_types
        )
        runner = TradingRunner(
            executor=dependency_provider.trading_cycle_executor,
            symbol=settings.market.symbol,
            interval=settings.market.interval,
            trade_mode=settings.app.trade_mode,
            candle_limit=max(100, minimum_candles),
            runtime_control=dependency_provider.runtime_control,
            runtime_observer=dependency_provider.runtime_reporter,
            multi_context_activation_precondition_provider=(
                dependency_provider.runtime_recovery_service
            ),
            autonomous_live_recovery_provider=(
                dependency_provider.runtime_recovery_service
            ),
            live_runtime_health_provider=(
                dependency_provider.live_runtime_health_service
            ),
            maximum_autonomous_live_recovery_attempts=1,
            autonomous_live_health_check_interval_seconds=1.0,
            maximum_consecutive_failures=3,
            failure_retry_delay_seconds=5.0,
            cycle_interval_seconds=(
                settings.market.discovery_cadence_seconds
                if settings.app.effective_execution_policy
                is ExecutionPolicy.AUTONOMOUS_LIVE
                else None
            ),
            global_discovery_telemetry=global_discovery_telemetry,
        )
        await run_until_restart(
            runner=runner,
            restart_coordinator=restart_coordinator,
        )
    finally:
        terminal_monitor.stop()
        await asyncio.gather(monitor_task, return_exceptions=True)


async def main() -> None:
    """Build and run the Botragram application."""
    settings_manager = SettingsManager()
    settings = settings_manager.load()
    arguments = tuple(sys.argv[1:])
    if arguments and arguments[0].strip().lower() == "backtest":
        from botragram.app.backtest_command import (
            format_backtest_report,
            parse_backtest_request,
            run_backtest_command,
        )

        request = parse_backtest_request(arguments=arguments)
        configure_logging(settings=settings.logging)

        try:
            result = await run_backtest_command(
                settings=settings,
                request=request,
            )
            print(format_backtest_report(result=result))
        finally:
            shutdown_logging()

        return

    restart_coordinator = RuntimeRestartCoordinator()
    market_type_confirmed = False
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
        while True:
            dependency_provider = DependencyProvider(
                database_path=settings.app.database_path,
                settings=settings,
                restart_coordinator=restart_coordinator,
                market_type_confirmed=market_type_confirmed,
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
                    restart_coordinator=restart_coordinator,
                ),
            )
            await application.run()
            requested_market_type = restart_coordinator.consume()

            if requested_market_type is None:
                break

            settings = replace(
                settings,
                exchange=replace(
                    settings.exchange,
                    market_type=requested_market_type,
                ),
            )
            settings_manager.validate(settings=settings)
            market_type_confirmed = True
            _LOGGER.info(
                "Application restarting with Binance market type: %s",
                requested_market_type.value,
            )
    finally:
        shutdown_logging()


if __name__ == "__main__":
    asyncio.run(main())
