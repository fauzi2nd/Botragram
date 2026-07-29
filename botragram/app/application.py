"""
Botragram

Description:
    Main application orchestrator.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
import asyncio
import logging

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.settings_manager import SettingsManager
from botragram.app.startup import initialize_logging
from botragram.config.app_settings import AppSettings
from botragram.engine.trading_engine import TradingEngine
from botragram.enums.exchange_type import ExchangeType
from botragram.exchanges.factory import create_exchange_client
from botragram.telegram.bot import TelegramBot

logger = logging.getLogger(__name__)


# =============================================================================
# Application Orchestrator Class
# =============================================================================
class Application:
    """Main orchestrator for the Botragram trading bot application."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        settings_manager: SettingsManager | None = None,
    ) -> None:
        """Initialize main Application.

        Args:
            settings: Optional AppSettings instance.
            settings_manager: Optional SettingsManager instance.
        """
        self._manager = settings_manager or SettingsManager()
        self._settings = settings or self._manager.load_app_settings()

        # Load config
        ex_settings = self._manager.load_exchange_settings()
        mkt_settings = self._manager.load_market_settings()
        risk_settings = self._manager.load_risk_settings()
        strat_settings = self._manager.load_strategy_settings()
        tg_settings = self._manager.load_telegram_settings()

        exchange_client = create_exchange_client(ex_settings)

        self._engine = TradingEngine(
            settings=self._settings,
            exchange_client=exchange_client,
            market_settings=mkt_settings,
            risk_settings=risk_settings,
            strategy_settings=strat_settings,
        )
        self._telegram_bot = TelegramBot(
            settings=tg_settings,
            engine=self._engine,
            application=self,
        )

    @property
    def engine(self) -> TradingEngine:
        """Get active trading engine instance.

        Returns:
            TradingEngine instance.
        """
        return self._engine

    async def switch_exchange(self, exchange_type: ExchangeType) -> None:
        """Hot-swap the active exchange client.

        Stops the engine, replaces the exchange client, then restarts.

        Args:
            exchange_type: ExchangeType to switch to.
        """
        logger.info(f"Switching exchange to: {exchange_type.value.upper()}")
        ex_settings = self._manager.load_exchange_settings(
            exchange_type=exchange_type
        )
        new_client = create_exchange_client(ex_settings)

        await self._engine.stop()
        self._engine.set_exchange_client(new_client)
        await self._engine.start()
        logger.info(f"Exchange switched to: {exchange_type.value.upper()}")

    async def run(self) -> None:
        """Run application lifecycle and maintain main event loop."""
        initialize_logging()
        logger.info(f"Starting Botragram v{self._settings.version}...")
        await self._engine.start()
        await self._telegram_bot.start()
        logger.info("Botragram application started successfully. Press Ctrl+C to exit.")

        try:
            while self._engine.is_running:
                await self._run_iteration()
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Shutdown signal received")
        finally:
            await self._telegram_bot.stop()
            await self._engine.stop()

    async def _run_iteration(self) -> None:
        """Process market data and then publish the latest state to Telegram."""
        try:
            await self._engine.process_tick()
        except Exception:
            logger.exception("Market-data update failed; retaining the last price")

        await self._telegram_bot.sync_engine_state()
